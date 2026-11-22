"""Core trial orchestrator: atomic per-trial JSON logging, concurrency, and `eval-retry`."""

from __future__ import annotations

import csv
import json
import os
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from eval_runner.agents import get_adapter
from eval_runner.container import (
    ContainerInfraError,
    ephemeral_container,
    exec_with_timeout,
    get_docker_client,
    put_directory,
    reap_orphan_containers,
)
from eval_runner.graders import grade_trial
from eval_runner.models import (
    InfraModelError,
    estimate_cost_usd,
    get_model_adapter,
    load_models_catalog,
    resolve_model,
)
from eval_runner.schemas import (
    ConfigSpec,
    GradeResult,
    ModelCatalog,
    ModelEntry,
    Settings,
    TaskSpec,
    TraceEvent,
    TrialResult,
    compute_config_hash,
)

DEFAULT_IMAGE = "agent-eval-base:latest"


def atomic_write_text(path: Path, text: str) -> None:
    """Write atomically via temp file + os.replace so partial crashes never corrupt JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def discover_tasks(tasks_path: Path) -> list[Path]:
    """Return a sorted list of task directories (supports either a single task or a folder)."""
    if (tasks_path / "instruction.md").exists():
        return [tasks_path]
    dirs = [p for p in sorted(tasks_path.iterdir()) if p.is_dir() and (p / "instruction.md").exists()]
    if not dirs:
        raise FileNotFoundError(f"No tasks (with instruction.md) found under {tasks_path}")
    return dirs


def _build_container_env(adapter: Any, config: ConfigSpec, model: ModelEntry) -> dict[str, str]:
    """Compose provider/auth env from the ModelAdapter and harness env from the HarnessAdapter."""
    model_adapter = get_model_adapter(model.adapter)
    return {
        **model_adapter.build_container_env(model),
        **adapter.get_container_env(config, model),
    }


def run_single_trial(
    *,
    experiment_id: str,
    task_dir: Path,
    config: ConfigSpec,
    model: ModelEntry,
    catalog: ModelCatalog,
    trial_index: int,
    results_dir: Path,
    skills_root: Path = Path("skills"),
    image: str | None = None,
) -> TrialResult:
    """Execute one isolated trial and atomically persist its result + trace."""
    task = TaskSpec.from_dir(task_dir)
    config_hash = compute_config_hash(config, model)
    trial_id = f"{config.name}_{config_hash}_{task.id}_t{trial_index}"
    trials_dir = results_dir / experiment_id / "trials"
    trial_json_path = trials_dir / f"{trial_id}.json"
    trace_path = trials_dir / f"{trial_id}.trace.jsonl"

    instruction = (task_dir / "instruction.md").read_text(encoding="utf-8").strip()
    adapter = get_adapter(config.harness)
    resolved_image = image or adapter.default_image
    timeout_sec = min(config.settings.timeout_sec, task.timeout_sec)

    start_time = time.time()
    try:
        env = _build_container_env(adapter, config, model)
        client = get_docker_client()
        try:
            with ephemeral_container(client, image=resolved_image, env=env) as container:
                # 1. Seed workspace fixtures (if any)
                fixtures_dir = task_dir / "fixtures"
                if fixtures_dir.exists():
                    put_directory(container, "/workspace", fixtures_dir)

                # 2. Let the harness adapter prepare spec, memory, and skills
                adapter.prepare_container(
                    container=container,
                    task_dir=task_dir,
                    instruction=instruction,
                    config=config,
                    model=model,
                    skills_root=skills_root,
                )

                # 3. Execute agent with real timeout watchdog
                cmd = adapter.build_command(config, model)
                exit_code, raw_output, timed_out = exec_with_timeout(
                    container, cmd, timeout_sec=timeout_sec, workdir="/workspace"
                )
                runtime_sec = round(time.time() - start_time, 2)

                result_data, events = adapter.extract_outputs(container)

                # Persist trace atomically
                if events:
                    trace_lines = "\n".join(ev.model_dump_json() for ev in events) + "\n"
                    atomic_write_text(trace_path, trace_lines)

                # Classify infrastructure / runner crash errors (Golden Rule: NEVER score as 0.0)
                if (
                    result_data.get("status") == "infra_error"
                    or exit_code == 2
                    or (not timed_out and (exit_code != 0 or not result_data))
                ):
                    err_msg = str(
                        result_data.get("error")
                        or f"Runner exited with code {exit_code} (no result.json). Output:\n{raw_output[-2000:]}"
                    )
                    trial = TrialResult(
                        trial_id=trial_id,
                        experiment_id=experiment_id,
                        config_name=config.name,
                        config_hash=config_hash,
                        harness=config.harness,
                        model=model.id,
                        task_id=task.id,
                        trial_index=trial_index,
                        status="infra_error",
                        runtime_sec=runtime_sec,
                        error_message=err_msg,
                        trace_path=str(trace_path) if events else None,
                    )
                    atomic_write_text(trial_json_path, trial.model_dump_json(indent=2))
                    return trial

                # Handle agent timeout (agent failure -> scored 0.0)
                if timed_out:
                    grade = GradeResult(
                        grader_type=task.grader.type,
                        score=0.0,
                        passed=False,
                        reasoning=f"Agent timed out after {timeout_sec}s.",
                    )
                else:
                    # 4. Run verifier ONLY after agent exits
                    grade = grade_trial(
                        container=container,
                        task_dir=task_dir,
                        task=task,
                        instruction=instruction,
                        final_answer=str(result_data.get("final_answer", "")),
                        catalog=catalog,
                    )

                in_tok = int(result_data.get("input_tokens", 0) or 0)
                out_tok = int(result_data.get("output_tokens", 0) or 0)
                cost_usd = estimate_cost_usd(model, in_tok, out_tok)

                trial = TrialResult(
                    trial_id=trial_id,
                    experiment_id=experiment_id,
                    config_name=config.name,
                    config_hash=config_hash,
                    harness=config.harness,
                    model=model.id,
                    task_id=task.id,
                    trial_index=trial_index,
                    status="completed",
                    score=grade.score,
                    passed=grade.passed,
                    runtime_sec=runtime_sec,
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                    cost_usd=cost_usd,
                    steps=int(result_data.get("steps", 0) or 0),
                    final_answer=str(result_data.get("final_answer", "")),
                    grade=grade,
                    trace_path=str(trace_path) if events else None,
                )
                atomic_write_text(trial_json_path, trial.model_dump_json(indent=2))
                return trial
        finally:
            client.close()
    except (ContainerInfraError, InfraModelError) as exc:
        trial = TrialResult(
            trial_id=trial_id,
            experiment_id=experiment_id,
            config_name=config.name,
            config_hash=config_hash,
            harness=config.harness,
            model=model.id,
            task_id=task.id,
            trial_index=trial_index,
            status="infra_error",
            runtime_sec=round(time.time() - start_time, 2),
            error_message=str(exc),
        )
        atomic_write_text(trial_json_path, trial.model_dump_json(indent=2))
        return trial


def save_experiment_manifest(
    exp_dir: Path,
    experiment_id: str,
    configs: list[tuple[ConfigSpec, ModelEntry]],
    task_dirs: list[Path],
    n_trials: int,
    seed: int,
) -> None:
    manifest = {
        "experiment_id": experiment_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "n_trials": n_trials,
        "seed": seed,
        "configs": [
            {
                "config": c.model_dump(mode="json"),
                "config_hash": compute_config_hash(c, m),
                "model": m.model_dump(mode="json"),
            }
            for c, m in configs
        ],
        "tasks": [str(p.resolve()) for p in task_dirs],
    }
    atomic_write_text(exp_dir / "manifest.json", json.dumps(manifest, indent=2))


def load_experiment_trials(exp_dir: Path) -> list[TrialResult]:
    trials_dir = exp_dir / "trials"
    if not trials_dir.exists():
        return []
    results: list[TrialResult] = []
    for p in sorted(trials_dir.glob("*.json")):
        results.append(TrialResult.model_validate_json(p.read_text(encoding="utf-8")))
    return results


def _slugify_model(model_ref: str) -> str:
    return model_ref.replace("/", "_").replace(":", "_")


def _load_base_settings(settings_path: Path | None) -> Settings:
    if settings_path is None:
        return Settings()
    import yaml

    raw = yaml.safe_load(settings_path.read_text(encoding="utf-8")) or {}
    if isinstance(raw, dict) and "settings" in raw:
        raw = raw["settings"] or {}
    return Settings.model_validate(raw)


def run_experiment(
    *,
    config_paths: list[Path] | None = None,
    harnesses: list[str] | None = None,
    models: list[str] | None = None,
    settings_path: Path | None = None,
    tasks_path: Path,
    n_trials: int = 1,
    concurrency: int = 2,
    seed: int = 42,
    experiment_id: str | None = None,
    models_path: Path = Path("models.yaml"),
    results_dir: Path = Path("results"),
    skills_root: Path = Path("skills"),
    image: str | None = None,
) -> tuple[str, list[TrialResult]]:
    """Run all (config × task × N) trials with randomized execution order.

    Supports either declarative `--config` YAML files, CLI `--harness` × `--model` matrix
    expansion (accepting catalog IDs or raw LiteLLM `provider/model` strings), or both.
    """
    catalog = load_models_catalog(models_path) if models_path.exists() else ModelCatalog(models=[])
    task_dirs = discover_tasks(tasks_path)
    resolved_configs: list[tuple[ConfigSpec, ModelEntry]] = []

    cfg_paths = list(config_paths or [])
    harness_list = list(harnesses or [])
    model_list = list(models or [])

    if cfg_paths and not harness_list and model_list:
        # Override models on the given template config(s)
        for cp in cfg_paths:
            base_cfg = ConfigSpec.from_yaml(cp)
            for m_ref in model_list:
                m_entry = resolve_model(catalog, m_ref)
                cfg = base_cfg.model_copy(
                    update={"name": f"{base_cfg.harness}-{_slugify_model(m_ref)}", "model": m_ref}
                )
                resolved_configs.append((cfg, m_entry))
    else:
        for cp in cfg_paths:
            cfg = ConfigSpec.from_yaml(cp)
            resolved_configs.append((cfg, resolve_model(catalog, cfg.model)))

        if harness_list or model_list:
            if not harness_list or not model_list:
                raise ValueError(
                    "Provide both --harness and --model for matrix runs (or pass --config)."
                )
            base_settings = _load_base_settings(settings_path)
            for h in harness_list:
                # Fail fast if harness isn't registered
                get_adapter(h)
                for m_ref in model_list:
                    m_entry = resolve_model(catalog, m_ref)
                    cfg = ConfigSpec(
                        name=f"{h}-{_slugify_model(m_ref)}",
                        harness=h,
                        model=m_ref,
                        settings=base_settings,
                    )
                    resolved_configs.append((cfg, m_entry))

    if not resolved_configs:
        raise ValueError("No configs to run. Pass --config or --harness + --model.")

    exp_id = experiment_id or f"exp_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    exp_dir = results_dir / exp_id
    exp_dir.mkdir(parents=True, exist_ok=True)
    save_experiment_manifest(exp_dir, exp_id, resolved_configs, task_dirs, n_trials, seed)

    # Clean up any orphaned containers from prior crashed runs
    try:
        reap_orphan_containers()
    except Exception:
        pass

    jobs: list[tuple[ConfigSpec, ModelEntry, Path, int]] = []
    for cfg, model in resolved_configs:
        for tdir in task_dirs:
            for idx in range(1, n_trials + 1):
                jobs.append((cfg, model, tdir, idx))

    # Randomize order across configs so provider drift doesn't bias one config
    rng = random.Random(seed)
    rng.shuffle(jobs)

    results: list[TrialResult] = []
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        futures = [
            pool.submit(
                run_single_trial,
                experiment_id=exp_id,
                task_dir=tdir,
                config=cfg,
                model=model,
                catalog=catalog,
                trial_index=idx,
                results_dir=results_dir,
                skills_root=skills_root,
                image=image,
            )
            for cfg, model, tdir, idx in jobs
        ]
        for fut in as_completed(futures):
            results.append(fut.result())

    return exp_id, results


def retry_experiment(
    *,
    experiment_id: str,
    concurrency: int = 2,
    models_path: Path = Path("models.yaml"),
    results_dir: Path = Path("results"),
    skills_root: Path = Path("skills"),
    image: str | None = None,
) -> list[TrialResult]:
    """Inspect-AI style `eval-retry`: re-run ONLY `infra_error` or missing trials."""
    exp_dir = results_dir / experiment_id
    manifest = json.loads((exp_dir / "manifest.json").read_text(encoding="utf-8"))
    catalog = load_models_catalog(models_path) if models_path.exists() else ModelCatalog(models=[])
    existing = {t.trial_id: t for t in load_experiment_trials(exp_dir)}

    to_run: list[tuple[ConfigSpec, ModelEntry, Path, int]] = []
    for entry in manifest["configs"]:
        cfg = ConfigSpec.model_validate(entry["config"])
        model = (
            ModelEntry.model_validate(entry["model"])
            if "model" in entry
            else resolve_model(catalog, cfg.model)
        )
        cfg_hash = compute_config_hash(cfg, model)
        for t_str in manifest["tasks"]:
            tdir = Path(t_str)
            task = TaskSpec.from_dir(tdir)
            for idx in range(1, int(manifest["n_trials"]) + 1):
                tid = f"{cfg.name}_{cfg_hash}_{task.id}_t{idx}"
                prev = existing.get(tid)
                if prev is None or prev.status == "infra_error":
                    to_run.append((cfg, model, tdir, idx))

    if not to_run:
        return []

    retried: list[TrialResult] = []
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        futures = [
            pool.submit(
                run_single_trial,
                experiment_id=experiment_id,
                task_dir=tdir,
                config=cfg,
                model=model,
                catalog=catalog,
                trial_index=idx,
                results_dir=results_dir,
                skills_root=skills_root,
                image=image,
            )
            for cfg, model, tdir, idx in to_run
        ]
        for fut in as_completed(futures):
            retried.append(fut.result())

    return retried


def export_experiment(exp_dir: Path, fmt: str, out_path: Path) -> None:
    """Export experiment trials to JSON or CSV."""
    trials = load_experiment_trials(exp_dir)
    if fmt == "json":
        payload = [t.model_dump(mode="json") for t in trials]
        atomic_write_text(out_path, json.dumps(payload, indent=2))
        return

    fieldnames = [
        "trial_id",
        "config_name",
        "config_hash",
        "harness",
        "model",
        "task_id",
        "trial_index",
        "status",
        "score",
        "passed",
        "runtime_sec",
        "input_tokens",
        "output_tokens",
        "cost_usd",
        "steps",
        "error_message",
    ]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for t in trials:
            row = t.model_dump(mode="json")
            writer.writerow({k: row.get(k) for k in fieldnames})
