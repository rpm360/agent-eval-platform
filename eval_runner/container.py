"""Ephemeral Docker container isolation, archive I/O, timeout watchdog, and cleanup."""

from __future__ import annotations

import contextlib
import io
import logging
import signal
import tarfile
import threading
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import docker
from docker.models.containers import Container

from eval_runner.constants import (
    CONTAINER_KILL_AFTER_SEC,
    CONTAINER_WATCHDOG_GRACE_SEC,
    MAX_CONTAINER_ARCHIVE_BYTES,
    TIMEOUT_EXIT_CODES,
)

logger = logging.getLogger(__name__)

MANAGED_LABEL = "aep.managed"
MAX_ARCHIVE_BYTES = MAX_CONTAINER_ARCHIVE_BYTES
TRIAL_UUID_HEX_LEN = 10
NANO_CPUS_PER_CORE = 1_000_000_000
DEFAULT_TMPFS_SIZE = "size=256M"
EXECUTABLE_FILE_MODE = 0o755
REGULAR_FILE_MODE = 0o644
TIMEOUT_FALLBACK_EXIT_CODE = 124


class ContainerInfraError(RuntimeError):
    """Raised on Docker daemon / container lifecycle failures (classified as `infra_error`)."""


def get_docker_client() -> docker.DockerClient:
    """Connect to the local Docker daemon via environment configuration."""
    try:
        return docker.from_env()
    except Exception as exc:
        raise ContainerInfraError(f"Failed to connect to Docker daemon: {exc}") from exc


def reap_orphan_containers(client: docker.DockerClient | None = None) -> int:
    """Force-remove any leftover managed containers from prior interrupted runs."""
    owns_client = client is None
    docker_client = client or get_docker_client()
    removed_count = 0
    try:
        orphan_containers = docker_client.containers.list(
            all=True, filters={"label": f"{MANAGED_LABEL}=true"}
        )
        for orphan_container in orphan_containers:
            try:
                orphan_container.remove(force=True, v=True)
                removed_count += 1
            except Exception as exc:
                logger.debug("Failed to remove orphan container %s: %s", orphan_container.id, exc)
    finally:
        if owns_client:
            docker_client.close()
    return removed_count


@contextlib.contextmanager
def ephemeral_container(
    client: docker.DockerClient,
    image: str,
    env: dict[str, str],
    mem_limit: str = "4g",
    cpus: float = 2.0,
    pids_limit: int = 256,
) -> Iterator[Container]:
    """Start an isolated container with tmpfs `/tmp` and guaranteed cleanup on exit or SIGINT."""
    trial_uuid = uuid.uuid4().hex[:TRIAL_UUID_HEX_LEN]
    try:
        container = client.containers.create(
            image=image,
            name=f"aep_trial_{trial_uuid}",
            command="sleep infinity",
            detach=True,
            environment=env,
            labels={MANAGED_LABEL: "true", "aep.trial_uuid": trial_uuid},
            mem_limit=mem_limit,
            nano_cpus=int(cpus * NANO_CPUS_PER_CORE),
            pids_limit=pids_limit,
            tmpfs={"/tmp": DEFAULT_TMPFS_SIZE},
        )
        container.start()
    except Exception as exc:
        raise ContainerInfraError(f"Failed to start container from '{image}': {exc}") from exc

    is_main_thread = threading.current_thread() is threading.main_thread()
    previous_sigint_handler: Any = None

    def _handle_abort(sig: int, frame: Any) -> None:
        try:
            container.remove(force=True, v=True)
        except Exception as exc:
            logger.debug("Failed to remove container on SIGINT: %s", exc)
        raise KeyboardInterrupt("Trial aborted by user")

    if is_main_thread:
        previous_sigint_handler = signal.signal(signal.SIGINT, _handle_abort)

    try:
        yield container
    finally:
        try:
            container.remove(force=True, v=True)
        except Exception as exc:
            logger.debug("Failed to remove ephemeral container %s: %s", trial_uuid, exc)
        if is_main_thread and previous_sigint_handler is not None:
            signal.signal(signal.SIGINT, previous_sigint_handler)


def put_files(container: Container, dest_dir: str, files: dict[str, bytes | str]) -> None:
    """Safely inject files into a container via an in-memory tar archive (zero shell escaping)."""
    if not files:
        return
    container.exec_run(["mkdir", "-p", dest_dir])
    archive_buffer = io.BytesIO()
    with tarfile.open(fileobj=archive_buffer, mode="w") as tar_archive:
        for rel_path, content in files.items():
            encoded_bytes = content.encode("utf-8") if isinstance(content, str) else content
            tar_info = tarfile.TarInfo(name=rel_path.lstrip("/"))
            tar_info.size = len(encoded_bytes)
            tar_info.mode = (
                EXECUTABLE_FILE_MODE if rel_path.endswith(".sh") else REGULAR_FILE_MODE
            )
            tar_archive.addfile(tar_info, io.BytesIO(encoded_bytes))
    archive_buffer.seek(0)
    container.put_archive(dest_dir, archive_buffer.getvalue())


def put_directory(container: Container, dest_dir: str, local_dir: Path) -> None:
    """Copy all files recursively under `local_dir` into `dest_dir` inside the container."""
    if not local_dir.exists():
        return
    directory_files: dict[str, bytes | str] = {
        str(source_file.relative_to(local_dir)): source_file.read_bytes()
        for source_file in local_dir.rglob("*")
        if source_file.is_file()
    }
    put_files(container, dest_dir, directory_files)


def get_file_text(container: Container, path: str) -> str | None:
    """Extract a single UTF-8 file from `container` safely with a hard archive-byte cap."""
    try:
        archive_stream, _ = container.get_archive(path)
    except Exception:
        return None

    archive_buffer = io.BytesIO()
    bytes_read = 0
    for chunk in archive_stream:
        bytes_read += len(chunk)
        if bytes_read > MAX_ARCHIVE_BYTES:
            logger.warning("Container file %s exceeded %d byte cap.", path, MAX_ARCHIVE_BYTES)
            return None
        archive_buffer.write(chunk)

    archive_buffer.seek(0)
    try:
        with tarfile.open(fileobj=archive_buffer, mode="r:*") as tar_archive:
            member = tar_archive.next()
            if member is None or not member.isfile():
                return None
            member_stream = tar_archive.extractfile(member)
            if member_stream is None:
                return None
            with member_stream:
                return member_stream.read().decode("utf-8", errors="replace")
    except (tarfile.TarError, OSError):
        return None


def exec_with_timeout(
    container: Container,
    cmd: list[str],
    timeout_sec: int,
    workdir: str = "/workspace",
) -> tuple[int, str, bool]:
    """Run `cmd` inside `container` guarded by both GNU `timeout` and a host-side watchdog.

    Returns `(exit_code, combined_output, timed_out)`.
    """
    wrapped_cmd = [
        "timeout",
        f"--kill-after={CONTAINER_KILL_AFTER_SEC}",
        str(timeout_sec),
        *cmd,
    ]
    watchdog_fired = threading.Event()

    def _kill_container() -> None:
        watchdog_fired.set()
        try:
            container.kill()
        except Exception as exc:
            logger.debug("Watchdog kill ignored on already-stopped container: %s", exc)

    watchdog_timer = threading.Timer(timeout_sec + CONTAINER_WATCHDOG_GRACE_SEC, _kill_container)
    watchdog_timer.daemon = True
    watchdog_timer.start()
    try:
        exec_result = container.exec_run(wrapped_cmd, workdir=workdir, demux=False)
        exit_code = int(exec_result.exit_code if exec_result.exit_code is not None else 1)
        decoded_output = (exec_result.output or b"").decode("utf-8", errors="replace")
    except Exception as exc:
        if watchdog_fired.is_set():
            return (
                TIMEOUT_FALLBACK_EXIT_CODE,
                f"Container killed by watchdog after {timeout_sec}s.",
                True,
            )
        raise ContainerInfraError(f"docker exec_run failed: {exc}") from exc
    finally:
        watchdog_timer.cancel()

    timed_out = watchdog_fired.is_set() or exit_code in TIMEOUT_EXIT_CODES
    return exit_code, decoded_output, timed_out
