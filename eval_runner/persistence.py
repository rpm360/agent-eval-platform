"""Atomic trial persistence, provenance metadata, and CSV/JSON experiment export."""

from __future__ import annotations

import csv
import hashlib
import importlib.metadata
import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from eval_runner.agents import get_adapter
from eval_runner.constants import EXPORT_CSV_COLUMNS, HASH_HEX_PREFIX_LEN
from eval_runner.container import ContainerInfraError, get_docker_client
from eval_runner.schemas import ConfigSpec, ModelEntry, TrialResult, compute_config_hash

logger = logging.getLogger(__name__)


def atomic_write_text(path: Path, text: str) -> None:
    """Write UTF-8 text atomically via temp file + rename, with VirtioFS bind-mount fallback."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    temp_path.write_text(text, encoding="utf-8")
    try:
        temp_path.replace(path)
    except FileNotFoundError:
        # Docker Desktop VirtioFS bind mounts can occasionally race on atomic rename.
        path.write_text(text, encoding="utf-8")
        try:
            temp_path.unlink(missing_ok=True)
        except OSError as exc:
            logger.debug("Failed to unlink fallback temp file %s: %s", temp_path, exc)


def collect_git_provenance() -> dict[str, str | bool | None]:
    """Capture current git HEAD commit SHA and working-tree dirty state when available."""
    try:
        commit_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
        status_output = subprocess.check_output(
            ["git", "status", "--porcelain"], text=True, stderr=subprocess.DEVNULL
        ).strip()
        return {"git_commit": commit_sha, "git_dirty": bool(status_output)}
    except (OSError, subprocess.SubprocessError):
        return {"git_commit": None, "git_dirty": None}


def hash_task_directory(task_dir: Path) -> str:
    """Compute a deterministic short SHA-256 digest over relative paths and contents in a task directory."""
    digest = hashlib.sha256()
    for file_path in sorted(task_dir.rglob("*")):
        if file_path.is_file():
            digest.update(str(file_path.relative_to(task_dir)).encode("utf-8"))
            digest.update(file_path.read_bytes())
    return digest.hexdigest()[:HASH_HEX_PREFIX_LEN]


def collect_image_digests(
    resolved_configs: list[tuple[ConfigSpec, ModelEntry]],
    override_image: str | None,
) -> dict[str, str]:
    """Resolve local Docker image IDs for each configured harness sandbox."""
    digests: dict[str, str] = {}
    try:
        docker_client = get_docker_client()
    except ContainerInfraError as exc:
        logger.debug("Skipping image digest lookup (Docker unavailable): %s", exc)
        return digests

    try:
        for harness_config, _ in resolved_configs:
            image_name = override_image or get_adapter(harness_config.harness).default_image
            if image_name in digests:
                continue
            try:
                digests[image_name] = docker_client.images.get(image_name).id or "unknown"
            except Exception as exc:  # docker.errors.ImageNotFound / APIError
                logger.debug("Could not inspect Docker image %s: %s", image_name, exc)
                digests[image_name] = "unavailable"
    finally:
        docker_client.close()
    return digests


def _resolve_litellm_version() -> str:
    try:
        return importlib.metadata.version("litellm")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def save_experiment_manifest(
    exp_dir: Path,
    experiment_id: str,
    configs: list[tuple[ConfigSpec, ModelEntry]],
    task_dirs: list[Path],
    n_trials: int,
    seed: int,
    override_image: str | None = None,
) -> None:
    """Write `manifest.json` capturing configs, task hashes, seed, and environment provenance."""
    manifest: dict[str, Any] = {
        "experiment_id": experiment_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "n_trials": n_trials,
        "seed": seed,
        "provenance": {
            **collect_git_provenance(),
            "litellm_version": _resolve_litellm_version(),
            "image_digests": collect_image_digests(configs, override_image),
            "task_hashes": {task_dir.name: hash_task_directory(task_dir) for task_dir in task_dirs},
        },
        "configs": [
            {
                "config": harness_config.model_dump(mode="json"),
                "config_hash": compute_config_hash(harness_config, model_entry),
                "model": model_entry.model_dump(mode="json"),
            }
            for harness_config, model_entry in configs
        ],
        "tasks": [str(task_dir.resolve()) for task_dir in task_dirs],
    }
    atomic_write_text(exp_dir / "manifest.json", json.dumps(manifest, indent=2))


def load_experiment_trials(exp_dir: Path) -> list[TrialResult]:
    """Load and validate all persisted per-trial JSON records under `<exp_dir>/trials/`."""
    trials_dir = exp_dir / "trials"
    if not trials_dir.exists():
        return []
    return [
        TrialResult.model_validate_json(trial_file.read_text(encoding="utf-8"))
        for trial_file in sorted(trials_dir.glob("*.json"))
    ]


def export_experiment(exp_dir: Path, fmt: str, out_path: Path) -> None:
    """Export persisted experiment trials to formatted JSON or flat CSV."""
    trials = load_experiment_trials(exp_dir)
    if fmt == "json":
        serialized_trials = [trial.model_dump(mode="json") for trial in trials]
        atomic_write_text(out_path, json.dumps(serialized_trials, indent=2))
        return

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=list(EXPORT_CSV_COLUMNS))
        writer.writeheader()
        for trial in trials:
            trial_row = trial.model_dump(mode="json")
            writer.writerow({col: trial_row.get(col) for col in EXPORT_CSV_COLUMNS})
