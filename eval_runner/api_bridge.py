"""JSON bridge for the TypeScript API so CLI and Web UI share exact stats, catalog, and failure logic."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import yaml

from eval_runner.agents import list_adapters
from eval_runner.calibration import load_latest_calibration
from eval_runner.failures import compare_failures, summarize_failures
from eval_runner.models import load_models_catalog
from eval_runner.runner import discover_tasks, load_experiment_trials
from eval_runner.schemas import TaskSpec
from eval_runner.stats import compare_configs, summarize_config


def cmd_catalog(root: Path) -> dict[str, Any]:
    models_path = root / "models.yaml"
    models = (
        [m.model_dump(mode="json") for m in load_models_catalog(models_path).models]
        if models_path.exists()
        else []
    )
    configs_dir = root / "configs"
    presets = []
    if configs_dir.exists():
        for p in sorted(configs_dir.glob("*.yaml")):
            presets.append(
                {
                    "name": p.stem,
                    "path": f"configs/{p.name}",
                    "settings": yaml.safe_load(p.read_text(encoding="utf-8")) or {},
                }
            )
    tasks_dir = root / "tasks"
    tasks = []
    if tasks_dir.exists():
        for td in discover_tasks(tasks_dir):
            spec = TaskSpec.from_dir(td)
            tasks.append(spec.model_dump(mode="json"))
    return {
        "harnesses": list_adapters(),
        "models": models,
        "presets": presets,
        "tasks": tasks,
    }


def cmd_analyze(root: Path, exp_id: str, a: str | None = None, b: str | None = None) -> dict[str, Any]:
    exp_dir = root / "results" / exp_id
    manifest_path = exp_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    trials = load_experiment_trials(exp_dir)

    by_cfg: dict[str, list] = {}
    for t in trials:
        by_cfg.setdefault(t.config_name, []).append(t)

    summaries = {name: summarize_config(ts) for name, ts in sorted(by_cfg.items())}
    names = sorted(by_cfg.keys())

    comparison = None
    failure_deltas: list[dict[str, Any]] = []
    if len(names) >= 2:
        name_a = a if a in by_cfg else names[0]
        name_b = b if b in by_cfg else (names[1] if names[1] != name_a else names[0])
        comparison = compare_configs(by_cfg[name_a], by_cfg[name_b], name_a, name_b)
        failure_deltas = compare_failures(by_cfg[name_a], by_cfg[name_b], name_a, name_b)

    judge_models = sorted(
        {
            str(t.grade.details.get("judge_model"))
            for t in trials
            if t.grade and t.grade.grader_type == "llm_judge" and isinstance(t.grade.details, dict)
            and t.grade.details.get("judge_model")
        }
    )
    calibrations = {
        jm: load_latest_calibration(jm, out_dir=root / "results" / "calibration")
        for jm in judge_models
    }

    return {
        "experiment_id": exp_id,
        "manifest": manifest,
        "config_names": names,
        "summaries": summaries,
        "comparison": comparison,
        "failures": summarize_failures(trials),
        "failure_deltas": failure_deltas,
        "calibrations": calibrations,
        "trial_count": len(trials),
    }


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    root = Path(args[args.index("--root") + 1]) if "--root" in args else Path(".")
    cmd = args[0] if args else ""
    if cmd == "catalog":
        print(json.dumps(cmd_catalog(root)))
        return 0
    if cmd == "analyze":
        exp_id = args[args.index("--exp") + 1]
        a = args[args.index("--a") + 1] if "--a" in args else None
        b = args[args.index("--b") + 1] if "--b" in args else None
        print(json.dumps(cmd_analyze(root, exp_id, a=a, b=b)))
        return 0
    print(json.dumps({"error": f"Unknown command: {cmd}"}), file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
