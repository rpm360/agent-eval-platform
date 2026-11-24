"""Task discovery, experiment ID slugging, and configuration matrix expansion."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import yaml

from eval_runner.agents import get_adapter
from eval_runner.constants import SLUG_ITEM_DISPLAY_LIMIT
from eval_runner.models import resolve_model
from eval_runner.schemas import ConfigSpec, ModelCatalog, ModelEntry, Settings


def discover_tasks(tasks_path: Path | list[Path]) -> list[Path]:
    """Return a deduplicated, sorted list of task directories containing `instruction.md`."""
    candidate_paths = list(tasks_path) if isinstance(tasks_path, (list, tuple)) else [tasks_path]
    seen_resolved: set[Path] = set()
    task_dirs: list[Path] = []

    def _add_if_new(directory: Path) -> None:
        resolved = directory.resolve()
        if resolved not in seen_resolved:
            seen_resolved.add(resolved)
            task_dirs.append(directory)

    for target_path in candidate_paths:
        if (target_path / "instruction.md").exists():
            _add_if_new(target_path)
            continue
        if target_path.exists() and target_path.is_dir():
            for child_dir in sorted(target_path.iterdir()):
                if child_dir.is_dir() and (child_dir / "instruction.md").exists():
                    _add_if_new(child_dir)

    if not task_dirs:
        raise FileNotFoundError(f"No tasks (with instruction.md) found under {tasks_path}")
    return task_dirs


def slugify_model_ref(model_ref: str) -> str:
    """Normalize `/` and `:` separators in raw model identifiers for config names."""
    return model_ref.replace("/", "_").replace(":", "_")


def sanitize_slug_part(value: str) -> str:
    """Replace non-filename-safe characters with hyphens for auto-generated experiment IDs."""
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-")


def load_base_settings(settings_path: Path | None) -> Settings:
    """Load shared `Settings` from an optional YAML preset (supporting top-level or nested `settings:`)."""
    if settings_path is None:
        return Settings()
    raw_yaml = yaml.safe_load(settings_path.read_text(encoding="utf-8")) or {}
    if isinstance(raw_yaml, dict) and "settings" in raw_yaml:
        raw_yaml = raw_yaml["settings"] or {}
    return Settings.model_validate(raw_yaml)


def _format_slug_items(items: list[str], limit: int = SLUG_ITEM_DISPLAY_LIMIT) -> str:
    if not items:
        return ""
    if len(items) <= limit:
        return "_".join(items)
    return f"{'_'.join(items[:limit])}_+{len(items) - limit}"


def build_default_experiment_id(resolved_configs: list[tuple[ConfigSpec, ModelEntry]]) -> str:
    """Construct a human-readable `<harnesses>__<models>__<timestamp>` experiment identifier."""
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    harness_slugs = list(
        dict.fromkeys(
            sanitize_slug_part(cfg.harness) for cfg, _ in resolved_configs if cfg.harness
        )
    )
    model_slugs = list(
        dict.fromkeys(
            sanitize_slug_part(model.id.rsplit("/", 1)[-1] if "/" in model.id else model.id)
            for _, model in resolved_configs
            if model.id
        )
    )
    parts = [
        part
        for part in (_format_slug_items(harness_slugs), _format_slug_items(model_slugs), timestamp)
        if part
    ]
    return "__".join(parts) if len(parts) > 1 else f"exp_{timestamp}"


def resolve_experiment_configs(
    *,
    catalog: ModelCatalog,
    config_paths: list[Path] | None = None,
    harnesses: list[str] | None = None,
    models: list[str] | None = None,
    settings_path: Path | None = None,
) -> list[tuple[ConfigSpec, ModelEntry]]:
    """Expand `--config` YAML files and/or `--harness` x `--model` CLI matrix flags."""
    cfg_paths = list(config_paths or [])
    harness_names = list(harnesses or [])
    model_refs = list(models or [])
    resolved_configs: list[tuple[ConfigSpec, ModelEntry]] = []

    # Case 1: Template config YAML(s) overridden across one or more models
    if cfg_paths and not harness_names and model_refs:
        for config_path in cfg_paths:
            base_config = ConfigSpec.from_yaml(config_path)
            for model_ref in model_refs:
                model_entry = resolve_model(catalog, model_ref)
                overridden_config = base_config.model_copy(
                    update={
                        "name": f"{base_config.harness}-{slugify_model_ref(model_ref)}",
                        "model": model_ref,
                    }
                )
                resolved_configs.append((overridden_config, model_entry))
        return resolved_configs

    # Case 2: Explicit config YAML files and/or harness x model Cartesian matrix
    for config_path in cfg_paths:
        harness_config = ConfigSpec.from_yaml(config_path)
        resolved_configs.append((harness_config, resolve_model(catalog, harness_config.model)))

    if harness_names or model_refs:
        if not harness_names or not model_refs:
            raise ValueError(
                "Provide both --harness and --model for matrix runs (or pass --config)."
            )
        shared_settings = load_base_settings(settings_path)
        for harness_name in harness_names:
            # Fail fast before launching containers if the harness adapter is unknown
            get_adapter(harness_name)
            for model_ref in model_refs:
                model_entry = resolve_model(catalog, model_ref)
                matrix_config = ConfigSpec(
                    name=f"{harness_name}-{slugify_model_ref(model_ref)}",
                    harness=harness_name,
                    model=model_ref,
                    settings=shared_settings,
                )
                resolved_configs.append((matrix_config, model_entry))

    if not resolved_configs:
        raise ValueError("No configs to run. Pass --config or --harness + --model.")
    return resolved_configs
