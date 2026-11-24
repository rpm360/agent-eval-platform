"""Core trial orchestrator: isolated sandbox execution, concurrency, and `eval-retry`."""

from __future__ import annotations

import json
import logging
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from docker.models.containers import Container

from eval_runner.agents import HarnessAdapter, get_adapter
from eval_runner.config_resolver import (
    build_default_experiment_id,
    discover_tasks,
    resolve_experiment_configs,
)
from eval_runner.constants import (
    DEFAULT_CONCURRENCY,
    DEFAULT_RANDOM_SEED,
    INFRA_ERROR_EXIT_CODE,
    MAX_STDIO_TAIL_CHARS,
    TRIAL_STREAM_PREFIX,
    TrialStatus,
)
from eval_runner.container import (
    ContainerInfraError,
    ephemeral_container,
    exec_with_timeout,
    get_docker_client,
    put_directory,
    reap_orphan_containers,
)
from eval_runner.failures import classify_failure
from eval_runner.graders import grade_trial
from eval_runner.models import (
    InfraModelError,
    estimate_cost_usd,
    get_model_adapter,
    load_models_catalog,
    resolve_model,
)
from eval_runner.persistence import (
    atomic_write_text,
    export_experiment,
    load_experiment_trials,
    save_experiment_manifest,
)
from eval_runner.schemas import (
    ConfigSpec,
    GradeResult,
    ModelCatalog,
    ModelEntry,
    TaskSpec,
    TraceEvent,
    TrialResult,
    compute_config_hash,
)

logger = logging.getLogger(__name__)

TrialJob = tuple[ConfigSpec, ModelEntry, Path, int]

__all__ = [
    "atomic_write_text",
    "discover_tasks",
    "export_experiment",
    "load_experiment_trials",
    "retry_experiment",
    "run_experiment",
    "run_single_trial",
    "save_experiment_manifest",
]


def _build_container_env(
    adapter: HarnessAdapter,
    config: ConfigSpec,
    model: ModelEntry,
) -> dict[str, str]:
    """Compose provider/auth env from the ModelAdapter and harness env from the HarnessAdapter."""
    model_adapter = get_model_adapter(model.adapter)
    return {
        **model_adapter.build_container_env(model),
        **adapter.get_container_env(config, model),
    }


def _format_trial_id(config_name: str, config_hash: str, task_id: str, trial_index: int) -> str:
    return f"{config_name}_{config_hash}_{task_id}_t{trial_index}"


def _is_runner_infra_failure(
    result_data: dict[str, Any],
    exit_code: int,
    timed_out: bool,
) -> bool:
    """Determine whether container execution failed due to infrastructure rather than agent logic."""
    if result_data.get("status") == TrialStatus.INFRA_ERROR:
        return True
    if exit_code == INFRA_ERROR_EXIT_CODE:
        return True
    return not timed_out and (exit_code != 0 or not result_data)


def _build_infra_error_trial(
    *,
    trial_id: str,
    experiment_id: str,
    config: ConfigSpec,
    config_hash: str,
    model_id: str,
    task_id: str,
    trial_index: int,
    runtime_sec: float,
    error_message: str,
    trace_path: Path | None = None,
) -> TrialResult:
    """Construct an `infra_error` TrialResult (Golden Rule: never score infra failures as 0.0)."""
    return TrialResult(
        trial_id=trial_id,
        experiment_id=experiment_id,
        config_name=config.name,
        config_hash=config_hash,
        harness=config.harness,
        model=model_id,
        task_id=task_id,
        trial_index=trial_index,
        status=TrialStatus.INFRA_ERROR,
        runtime_sec=runtime_sec,
        failure_category=TrialStatus.INFRA_ERROR,
        error_message=error_message,
        trace_path=str(trace_path) if trace_path is not None else None,
    )


def _evaluate_completed_container(
    *,
    container: Container,
    task_dir: Path,
    task: TaskSpec,
    instruction: str,
    config: ConfigSpec,
    catalog: ModelCatalog,
    final_answer: str,
    total_tokens: int,
    timed_out: bool,
    timeout_sec: int,
) -> GradeResult:
    """Enforce token/timeout guardrails first; otherwise invoke the configured task grader."""
    token_budget = config.settings.max_total_tokens
    if token_budget is not None and total_tokens > token_budget:
        return GradeResult(
            grader_type=task.grader.type,
            score=0.0,
            passed=False,
            reasoning=f"Token budget exceeded: {total_tokens} > max_total_tokens ({token_budget}).",
        )
    if timed_out:
        return GradeResult(
            grader_type=task.grader.type,
            score=0.0,
            passed=False,
            reasoning=f"Agent timed out after {timeout_sec}s.",
        )
    return grade_trial(
        container=container,
        task_dir=task_dir,
        task=task,
        instruction=instruction,
        final_answer=final_answer,
        catalog=catalog,
    )


def _persist_trace_events(trace_path: Path, events: list[TraceEvent]) -> None:
    if not events:
        return
    serialized_lines = "\n".join(event.model_dump_json() for event in events) + "\n"
    atomic_write_text(trace_path, serialized_lines)


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
    """Execute one isolated container trial and atomically persist its result and trajectory."""
    task = TaskSpec.from_dir(task_dir)
    config_hash = compute_config_hash(config, model)
    trial_id = _format_trial_id(config.name, config_hash, task.id, trial_index)
    trials_dir = results_dir / experiment_id / "trials"
    trial_json_path = trials_dir / f"{trial_id}.json"
    trace_path = trials_dir / f"{trial_id}.trace.jsonl"

    instruction = (task_dir / "instruction.md").read_text(encoding="utf-8").strip()
    adapter = get_adapter(config.harness)
    resolved_image = image or adapter.default_image
    timeout_sec = min(config.settings.timeout_sec, task.timeout_sec)

    start_time = time.time()
    try:
        container_env = _build_container_env(adapter, config, model)
        docker_client = get_docker_client()
        try:
            with ephemeral_container(docker_client, image=resolved_image, env=container_env) as container:
                fixtures_dir = task_dir / "fixtures"
                if fixtures_dir.exists():
                    put_directory(container, "/workspace", fixtures_dir)

                adapter.prepare_container(
                    container=container,
                    task_dir=task_dir,
                    instruction=instruction,
                    config=config,
                    model=model,
                    skills_root=skills_root,
                )

                command = adapter.build_command(config, model)
                exit_code, raw_output, timed_out = exec_with_timeout(
                    container, command, timeout_sec=timeout_sec, workdir="/workspace"
                )
                runtime_sec = round(time.time() - start_time, 2)

                result_data, trace_events = adapter.extract_outputs(container)
                _persist_trace_events(trace_path, trace_events)
                persisted_trace = trace_path if trace_events else None

                if _is_runner_infra_failure(result_data, exit_code, timed_out):
                    output_tail = raw_output[-MAX_STDIO_TAIL_CHARS:]
                    error_message = str(
                        result_data.get("error")
                        or f"Runner exited with code {exit_code} (no result.json). Output:\n{output_tail}"
                    )
                    infra_trial = _build_infra_error_trial(
                        trial_id=trial_id,
                        experiment_id=experiment_id,
                        config=config,
                        config_hash=config_hash,
                        model_id=model.id,
                        task_id=task.id,
                        trial_index=trial_index,
                        runtime_sec=runtime_sec,
                        error_message=error_message,
                        trace_path=persisted_trace,
                    )
                    atomic_write_text(trial_json_path, infra_trial.model_dump_json(indent=2))
                    return infra_trial

                input_tokens = int(result_data.get("input_tokens", 0) or 0)
                output_tokens = int(result_data.get("output_tokens", 0) or 0)
                total_tokens = input_tokens + output_tokens
                cost_usd = estimate_cost_usd(model, input_tokens, output_tokens)
                final_answer = str(result_data.get("final_answer", ""))

                grade = _evaluate_completed_container(
                    container=container,
                    task_dir=task_dir,
                    task=task,
                    instruction=instruction,
                    config=config,
                    catalog=catalog,
                    final_answer=final_answer,
                    total_tokens=total_tokens,
                    timed_out=timed_out,
                    timeout_sec=timeout_sec,
                )

                completed_trial = TrialResult(
                    trial_id=trial_id,
                    experiment_id=experiment_id,
                    config_name=config.name,
                    config_hash=config_hash,
                    harness=config.harness,
                    model=model.id,
                    task_id=task.id,
                    trial_index=trial_index,
                    status=TrialStatus.COMPLETED,
                    score=grade.score,
                    passed=grade.passed,
                    runtime_sec=runtime_sec,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost_usd=cost_usd,
                    steps=int(result_data.get("steps", 0) or 0),
                    final_answer=final_answer,
                    grade=grade,
                    trace_path=str(persisted_trace) if persisted_trace is not None else None,
                )
                failure_category = classify_failure(
                    completed_trial, trace_events, task, config.settings
                )
                if failure_category is not None:
                    completed_trial = completed_trial.model_copy(
                        update={"failure_category": failure_category}
                    )
                atomic_write_text(trial_json_path, completed_trial.model_dump_json(indent=2))
                return completed_trial
        finally:
            docker_client.close()
    except (ContainerInfraError, InfraModelError) as exc:
        infra_trial = _build_infra_error_trial(
            trial_id=trial_id,
            experiment_id=experiment_id,
            config=config,
            config_hash=config_hash,
            model_id=model.id,
            task_id=task.id,
            trial_index=trial_index,
            runtime_sec=round(time.time() - start_time, 2),
            error_message=str(exc),
        )
        atomic_write_text(trial_json_path, infra_trial.model_dump_json(indent=2))
        return infra_trial


def _emit_trial_stream_event(experiment_id: str, trial: TrialResult) -> None:
    """Emit structured progress line on stdout consumed by the API/Web SSE job stream."""
    payload = {
        "experiment_id": experiment_id,
        "trial_id": trial.trial_id,
        "status": trial.status,
        "passed": trial.passed,
        "score": trial.score,
    }
    sys.stdout.write(f"{TRIAL_STREAM_PREFIX} {json.dumps(payload)}\n")
    sys.stdout.flush()


def _execute_trial_jobs(
    *,
    experiment_id: str,
    jobs: list[TrialJob],
    catalog: ModelCatalog,
    concurrency: int,
    results_dir: Path,
    skills_root: Path,
    image: str | None,
) -> list[TrialResult]:
    """Run scheduled trial jobs across a bounded worker pool and stream completions."""
    completed_results: list[TrialResult] = []
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as worker_pool:
        futures = [
            worker_pool.submit(
                run_single_trial,
                experiment_id=experiment_id,
                task_dir=task_dir,
                config=harness_config,
                model=model_entry,
                catalog=catalog,
                trial_index=trial_idx,
                results_dir=results_dir,
                skills_root=skills_root,
                image=image,
            )
            for harness_config, model_entry, task_dir, trial_idx in jobs
        ]
        for future in as_completed(futures):
            trial_result = future.result()
            completed_results.append(trial_result)
            _emit_trial_stream_event(experiment_id, trial_result)
    return completed_results


def run_experiment(
    *,
    config_paths: list[Path] | None = None,
    harnesses: list[str] | None = None,
    models: list[str] | None = None,
    settings_path: Path | None = None,
    tasks_path: Path | list[Path] = Path("tasks"),
    n_trials: int = 1,
    concurrency: int = DEFAULT_CONCURRENCY,
    seed: int = DEFAULT_RANDOM_SEED,
    experiment_id: str | None = None,
    models_path: Path = Path("models.yaml"),
    results_dir: Path = Path("results"),
    skills_root: Path = Path("skills"),
    image: str | None = None,
) -> tuple[str, list[TrialResult]]:
    """Run all `(config x task x N)` trials in randomized order to avoid provider-drift bias."""
    catalog = load_models_catalog(models_path) if models_path.exists() else ModelCatalog(models=[])
    task_dirs = discover_tasks(tasks_path)
    resolved_configs = resolve_experiment_configs(
        catalog=catalog,
        config_paths=config_paths,
        harnesses=harnesses,
        models=models,
        settings_path=settings_path,
    )

    exp_id = experiment_id or build_default_experiment_id(resolved_configs)
    exp_dir = results_dir / exp_id
    exp_dir.mkdir(parents=True, exist_ok=True)
    save_experiment_manifest(
        exp_dir, exp_id, resolved_configs, task_dirs, n_trials, seed, override_image=image
    )

    try:
        reap_orphan_containers()
    except ContainerInfraError as exc:
        logger.debug("Skipping orphan container cleanup: %s", exc)

    jobs: list[TrialJob] = [
        (harness_config, model_entry, task_dir, trial_idx)
        for harness_config, model_entry in resolved_configs
        for task_dir in task_dirs
        for trial_idx in range(1, n_trials + 1)
    ]
    random.Random(seed).shuffle(jobs)

    results = _execute_trial_jobs(
        experiment_id=exp_id,
        jobs=jobs,
        catalog=catalog,
        concurrency=concurrency,
        results_dir=results_dir,
        skills_root=skills_root,
        image=image,
    )
    return exp_id, results


def retry_experiment(
    *,
    experiment_id: str,
    concurrency: int = DEFAULT_CONCURRENCY,
    models_path: Path = Path("models.yaml"),
    results_dir: Path = Path("results"),
    skills_root: Path = Path("skills"),
    image: str | None = None,
) -> list[TrialResult]:
    """Re-run ONLY `infra_error` or missing trials from an existing experiment manifest."""
    exp_dir = results_dir / experiment_id
    manifest = json.loads((exp_dir / "manifest.json").read_text(encoding="utf-8"))
    catalog = load_models_catalog(models_path) if models_path.exists() else ModelCatalog(models=[])
    existing_by_id = {trial.trial_id: trial for trial in load_experiment_trials(exp_dir)}

    pending_jobs: list[TrialJob] = []
    n_trials = int(manifest["n_trials"])
    for config_entry in manifest["configs"]:
        harness_config = ConfigSpec.model_validate(config_entry["config"])
        model_entry = (
            ModelEntry.model_validate(config_entry["model"])
            if "model" in config_entry
            else resolve_model(catalog, harness_config.model)
        )
        config_hash = compute_config_hash(harness_config, model_entry)
        for task_path_str in manifest["tasks"]:
            task_dir = Path(task_path_str)
            task = TaskSpec.from_dir(task_dir)
            for trial_idx in range(1, n_trials + 1):
                trial_id = _format_trial_id(harness_config.name, config_hash, task.id, trial_idx)
                previous_trial = existing_by_id.get(trial_id)
                if previous_trial is None or previous_trial.status == TrialStatus.INFRA_ERROR:
                    pending_jobs.append((harness_config, model_entry, task_dir, trial_idx))

    if not pending_jobs:
        return []

    return _execute_trial_jobs(
        experiment_id=experiment_id,
        jobs=pending_jobs,
        catalog=catalog,
        concurrency=concurrency,
        results_dir=results_dir,
        skills_root=skills_root,
        image=image,
    )
