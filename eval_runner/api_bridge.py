"""JSON bridge for the TypeScript API so CLI and Web UI share exact stats, catalog, and failure logic."""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

from eval_runner.agents import list_adapters
from eval_runner.calibration import load_latest_calibration
from eval_runner.constants import GraderType, INFRA_ERROR_EXIT_CODE
from eval_runner.failures import compare_failures, summarize_failures
from eval_runner.models import load_models_catalog
from eval_runner.runner import discover_tasks, load_experiment_trials
from eval_runner.schemas import TaskSpec, TrialResult
from eval_runner.stats import compare_configs, summarize_config


def _load_presets(configs_dir: Path) -> list[dict[str, Any]]:
    if not configs_dir.exists():
        return []
    return [
        {
            "name": preset_path.stem,
            "path": f"configs/{preset_path.name}",
            "settings": yaml.safe_load(preset_path.read_text(encoding="utf-8")) or {},
        }
        for preset_path in sorted(configs_dir.glob("*.yaml"))
    ]


def _load_tasks_catalog(tasks_dir: Path) -> list[dict[str, Any]]:
    if not tasks_dir.exists():
        return []
    return [
        TaskSpec.from_dir(task_dir).model_dump(mode="json")
        for task_dir in discover_tasks(tasks_dir)
    ]


def cmd_catalog(root: Path) -> dict[str, Any]:
    """Return registered harnesses, catalog models, config presets, and task metadata."""
    models_path = root / "models.yaml"
    models = (
        [entry.model_dump(mode="json") for entry in load_models_catalog(models_path).models]
        if models_path.exists()
        else []
    )
    return {
        "harnesses": list_adapters(),
        "models": models,
        "presets": _load_presets(root / "configs"),
        "tasks": _load_tasks_catalog(root / "tasks"),
    }


def _collect_judge_calibrations(
    trials: list[TrialResult],
    calibration_dir: Path,
) -> dict[str, dict[str, Any] | None]:
    judge_models = sorted(
        {
            str(trial.grade.details.get("judge_model"))
            for trial in trials
            if trial.grade
            and trial.grade.grader_type == GraderType.LLM_JUDGE
            and isinstance(trial.grade.details, dict)
            and trial.grade.details.get("judge_model")
        }
    )
    return {
        judge_model: load_latest_calibration(judge_model, out_dir=calibration_dir)
        for judge_model in judge_models
    }


def cmd_analyze(
    root: Path,
    exp_id: str,
    a: str | None = None,
    b: str | None = None,
) -> dict[str, Any]:
    """Aggregate experiment summaries, paired statistical comparisons, failures, and judge calibrations."""
    exp_dir = root / "results" / exp_id
    manifest_path = exp_dir / "manifest.json"
    manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    )
    trials = load_experiment_trials(exp_dir)

    trials_by_config: dict[str, list[TrialResult]] = defaultdict(list)
    for trial in trials:
        trials_by_config[trial.config_name].append(trial)

    config_names = sorted(trials_by_config.keys())
    summaries = {
        config_name: summarize_config(trials_by_config[config_name])
        for config_name in config_names
    }

    comparison: dict[str, Any] | None = None
    failure_deltas: list[dict[str, Any]] = []
    if len(config_names) >= 2:
        name_a = a if a in trials_by_config else config_names[0]
        name_b = (
            b
            if b in trials_by_config
            else (config_names[1] if config_names[1] != name_a else config_names[0])
        )
        comparison = compare_configs(
            trials_by_config[name_a], trials_by_config[name_b], name_a, name_b
        )
        failure_deltas = compare_failures(
            trials_by_config[name_a], trials_by_config[name_b], name_a, name_b
        )

    return {
        "experiment_id": exp_id,
        "manifest": manifest,
        "config_names": config_names,
        "summaries": summaries,
        "comparison": comparison,
        "failures": summarize_failures(trials),
        "failure_deltas": failure_deltas,
        "calibrations": _collect_judge_calibrations(trials, root / "results" / "calibration"),
        "trial_count": len(trials),
    }


def _read_flag_value(args: list[str], flag: str) -> str | None:
    if flag not in args:
        return None
    flag_index = args.index(flag)
    return args[flag_index + 1] if (flag_index + 1) < len(args) else None


def main(argv: list[str] | None = None) -> int:
    """Entrypoint invoked by `api/src/server.ts` (`python -m eval_runner.api_bridge ...`)."""
    args = list(sys.argv[1:] if argv is None else argv)
    root_arg = _read_flag_value(args, "--root")
    root_dir = Path(root_arg) if root_arg is not None else Path(".")
    subcommand = args[0] if args else ""

    if subcommand == "catalog":
        sys.stdout.write(json.dumps(cmd_catalog(root_dir)) + "\n")
        return 0

    if subcommand == "analyze":
        exp_id = _read_flag_value(args, "--exp") or ""
        config_a = _read_flag_value(args, "--a")
        config_b = _read_flag_value(args, "--b")
        sys.stdout.write(json.dumps(cmd_analyze(root_dir, exp_id, a=config_a, b=config_b)) + "\n")
        return 0

    sys.stderr.write(json.dumps({"error": f"Unknown command: {subcommand}"}) + "\n")
    return INFRA_ERROR_EXIT_CODE


if __name__ == "__main__":
    raise SystemExit(main())
