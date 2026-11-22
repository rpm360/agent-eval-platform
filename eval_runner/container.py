"""Ephemeral Docker container isolation, archive I/O, timeout watchdog, and cleanup."""

from __future__ import annotations

import contextlib
import io
import signal
import tarfile
import threading
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import docker
from docker.models.containers import Container

MANAGED_LABEL = "aep.managed"
MAX_ARCHIVE_BYTES = 20 * 1024 * 1024  # 20 MB cap when pulling files from containers


class ContainerInfraError(RuntimeError):
    """Raised on Docker daemon / container lifecycle failures (classified as infra_error)."""


def get_docker_client() -> docker.DockerClient:
    try:
        return docker.from_env()
    except Exception as exc:
        raise ContainerInfraError(f"Failed to connect to Docker daemon: {exc}") from exc


def reap_orphan_containers(client: docker.DockerClient | None = None) -> int:
    """Remove any leftover containers from prior crashed runs."""
    own_client = client is None
    client = client or get_docker_client()
    removed = 0
    try:
        orphans = client.containers.list(all=True, filters={"label": f"{MANAGED_LABEL}=true"})
        for c in orphans:
            try:
                c.remove(force=True, v=True)
                removed += 1
            except Exception:
                pass
    finally:
        if own_client:
            client.close()
    return removed


@contextlib.contextmanager
def ephemeral_container(
    client: docker.DockerClient,
    image: str,
    env: dict[str, str],
    mem_limit: str = "4g",
    cpus: float = 2.0,
    pids_limit: int = 256,
) -> Iterator[Container]:
    """Start an isolated container with tmpfs workspace and guaranteed cleanup on exit/SIGINT."""
    trial_uuid = uuid.uuid4().hex[:10]
    try:
        container = client.containers.create(
            image=image,
            name=f"aep_trial_{trial_uuid}",
            command="sleep infinity",
            detach=True,
            environment=env,
            labels={MANAGED_LABEL: "true", "aep.trial_uuid": trial_uuid},
            mem_limit=mem_limit,
            nano_cpus=int(cpus * 1_000_000_000),
            pids_limit=pids_limit,
            tmpfs={"/tmp": "size=256M"},
        )
        container.start()
    except Exception as exc:
        raise ContainerInfraError(f"Failed to start container from '{image}': {exc}") from exc

    is_main_thread = threading.current_thread() is threading.main_thread()
    old_sigint: Any = None

    def _handle_abort(sig: int, frame: Any) -> None:
        try:
            container.remove(force=True, v=True)
        except Exception:
            pass
        raise KeyboardInterrupt("Trial aborted by user")

    if is_main_thread:
        old_sigint = signal.signal(signal.SIGINT, _handle_abort)

    try:
        yield container
    finally:
        try:
            container.remove(force=True, v=True)
        except Exception:
            pass
        if is_main_thread and old_sigint is not None:
            signal.signal(signal.SIGINT, old_sigint)


def put_files(container: Container, dest_dir: str, files: dict[str, bytes | str]) -> None:
    """Safely inject files into a container via in-memory tar archive (no shell escaping)."""
    if not files:
        return
    container.exec_run(["mkdir", "-p", dest_dir])
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for rel_path, content in files.items():
            raw = content.encode("utf-8") if isinstance(content, str) else content
            info = tarfile.TarInfo(name=rel_path.lstrip("/"))
            info.size = len(raw)
            info.mode = 0o755 if rel_path.endswith(".sh") else 0o644
            tar.addfile(info, io.BytesIO(raw))
    buf.seek(0)
    container.put_archive(dest_dir, buf.getvalue())


def put_directory(container: Container, dest_dir: str, local_dir: Path) -> None:
    """Copy all files under a local directory into `dest_dir` inside the container."""
    if not local_dir.exists():
        return
    files: dict[str, bytes] = {}
    for p in local_dir.rglob("*"):
        if p.is_file():
            files[str(p.relative_to(local_dir))] = p.read_bytes()
    put_files(container, dest_dir, files)


def get_file_text(container: Container, path: str) -> str | None:
    """Extract a single file from the container safely with a size cap."""
    try:
        stream, _ = container.get_archive(path)
    except Exception:
        return None
    buf = io.BytesIO()
    total = 0
    for chunk in stream:
        total += len(chunk)
        if total > MAX_ARCHIVE_BYTES:
            return None
        buf.write(chunk)
    buf.seek(0)
    try:
        with tarfile.open(fileobj=buf, mode="r:*") as tar:
            member = tar.next()
            if member is None or not member.isfile():
                return None
            f = tar.extractfile(member)
            return f.read().decode("utf-8", errors="replace") if f else None
    except Exception:
        return None


def exec_with_timeout(
    container: Container,
    cmd: list[str],
    timeout_sec: int,
    workdir: str = "/workspace",
) -> tuple[int, str, bool]:
    """Run a command inside the container with both in-container `timeout` and a hard watchdog.

    Returns (exit_code, combined_output, timed_out).
    """
    wrapped = ["timeout", "--kill-after=5", str(timeout_sec), *cmd]
    watchdog_fired = threading.Event()

    def _kill_container() -> None:
        watchdog_fired.set()
        try:
            container.kill()
        except Exception:
            pass

    timer = threading.Timer(timeout_sec + 15, _kill_container)
    timer.daemon = True
    timer.start()
    try:
        res = container.exec_run(wrapped, workdir=workdir, demux=False)
        exit_code = int(res.exit_code if res.exit_code is not None else 1)
        output = (res.output or b"").decode("utf-8", errors="replace")
    except Exception as exc:
        if watchdog_fired.is_set():
            return 124, f"Container killed by watchdog after {timeout_sec}s.", True
        raise ContainerInfraError(f"docker exec_run failed: {exc}") from exc
    finally:
        timer.cancel()

    timed_out = watchdog_fired.is_set() or exit_code in (124, 137)
    return exit_code, output, timed_out
