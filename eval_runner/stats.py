"""Statistical comparison: paired bootstrap 95% CI, exact McNemar test, and per-task deltas."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import numpy as np
from scipy.stats import binomtest, bootstrap

from eval_runner.constants import (
    DEFAULT_RANDOM_SEED,
    HIGH_INFRA_ERROR_RATE_THRESHOLD,
    MAJORITY_PASS_SCORE_THRESHOLD,
    MIN_POWERED_SHARED_TASKS,
    MIN_POWERED_TRIALS_PER_TASK,
    SATURATED_SCORE_HIGH,
    SATURATED_SCORE_LOW,
    TrialStatus,
)
from eval_runner.schemas import TrialResult

DEFAULT_CONFIDENCE_LEVEL = 0.95
DEFAULT_BOOTSTRAP_RESAMPLES = 10_000


def exact_mcnemar_pvalue(a_pass: list[bool], b_pass: list[bool]) -> float:
    """Compute the two-sided exact binomial McNemar p-value on paired pass/fail outcomes."""
    b_only_wins = sum(1 for passed_a, passed_b in zip(a_pass, b_pass) if (not passed_a) and passed_b)
    a_only_wins = sum(1 for passed_a, passed_b in zip(a_pass, b_pass) if passed_a and (not passed_b))
    discordant_pairs = a_only_wins + b_only_wins
    if discordant_pairs == 0:
        return 1.0
    test_result = binomtest(
        min(a_only_wins, b_only_wins), discordant_pairs, 0.5, alternative="two-sided"
    )
    return float(test_result.pvalue)


def paired_bootstrap_ci(
    deltas: list[float],
    confidence_level: float = DEFAULT_CONFIDENCE_LEVEL,
    n_resamples: int = DEFAULT_BOOTSTRAP_RESAMPLES,
    seed: int = DEFAULT_RANDOM_SEED,
) -> tuple[float, float]:
    """Compute percentile paired bootstrap confidence bounds for the mean of per-task deltas (`B - A`)."""
    delta_array = np.asarray(deltas, dtype=float)
    if delta_array.size == 0:
        return (0.0, 0.0)
    if delta_array.size == 1 or np.allclose(delta_array, delta_array[0]):
        constant_val = float(delta_array[0])
        return (constant_val, constant_val)

    rng = np.random.default_rng(seed)
    bootstrap_result = bootstrap(
        (delta_array,),
        np.mean,
        confidence_level=confidence_level,
        n_resamples=n_resamples,
        method="percentile",
        random_state=rng,
    )
    return (
        float(bootstrap_result.confidence_interval.low),
        float(bootstrap_result.confidence_interval.high),
    )


def _empty_config_summary(infra_error_count: int) -> dict[str, Any]:
    return {
        "completed": 0,
        "infra_errors": infra_error_count,
        "mean_score": 0.0,
        "pass_rate": 0.0,
        "avg_cost_usd": 0.0,
        "total_cost_usd": 0.0,
        "cost_per_pass_usd": None,
        "avg_runtime_sec": 0.0,
        "p50_runtime_sec": 0.0,
        "p95_runtime_sec": 0.0,
        "avg_tokens": 0,
    }


def summarize_config(trials: list[TrialResult]) -> dict[str, Any]:
    """Aggregate quality, cost, runtime percentile, and token metrics over completed trials."""
    completed_trials = [
        trial
        for trial in trials
        if trial.status == TrialStatus.COMPLETED and trial.score is not None
    ]
    errored_trials = [trial for trial in trials if trial.status == TrialStatus.INFRA_ERROR]
    if not completed_trials:
        return _empty_config_summary(len(errored_trials))

    runtimes = np.array([trial.runtime_sec for trial in completed_trials], dtype=float)
    scores = [float(trial.score) for trial in completed_trials if trial.score is not None]
    costs = [trial.cost_usd for trial in completed_trials]
    total_cost = float(np.sum(costs))
    passed_count = sum(1 for trial in completed_trials if trial.passed)
    token_totals = [trial.input_tokens + trial.output_tokens for trial in completed_trials]

    return {
        "completed": len(completed_trials),
        "infra_errors": len(errored_trials),
        "mean_score": round(float(np.mean(scores)), 4),
        "pass_rate": round(float(passed_count / len(completed_trials)), 4),
        "avg_cost_usd": round(float(np.mean(costs)), 6),
        "total_cost_usd": round(total_cost, 6),
        "cost_per_pass_usd": round(total_cost / passed_count, 6) if passed_count else None,
        "avg_runtime_sec": round(float(np.mean(runtimes)), 2),
        "p50_runtime_sec": round(float(np.percentile(runtimes, 50)), 2),
        "p95_runtime_sec": round(float(np.percentile(runtimes, 95)), 2),
        "avg_tokens": int(np.mean(token_totals)),
    }


def _is_saturated_task_row(task_row: dict[str, Any]) -> bool:
    both_ceiling = (
        task_row["score_a"] >= SATURATED_SCORE_HIGH
        and task_row["score_b"] >= SATURATED_SCORE_HIGH
    )
    both_floor = (
        task_row["score_a"] <= SATURATED_SCORE_LOW
        and task_row["score_b"] <= SATURATED_SCORE_LOW
    )
    return both_ceiling or both_floor


def power_warnings(report: dict[str, Any]) -> list[str]:
    """Flag under-powered or biased comparisons so small-sample noise isn't over-interpreted."""
    warnings: list[str] = []
    shared_tasks = int(report.get("shared_tasks", 0))
    if shared_tasks < MIN_POWERED_SHARED_TASKS:
        warnings.append(
            f"Low task count ({shared_tasks} shared task(s) < {MIN_POWERED_SHARED_TASKS}): "
            "paired bootstrap CI has wide uncertainty."
        )

    per_task_rows = report.get("per_task", [])
    if per_task_rows:
        min_trials = min(min(task_row["n_a"], task_row["n_b"]) for task_row in per_task_rows)
        if min_trials < MIN_POWERED_TRIALS_PER_TASK:
            warnings.append(
                f"Low trial count per task (min n={min_trials} < {MIN_POWERED_TRIALS_PER_TASK}): "
                "single-trial variance may dominate."
            )
        saturated_count = sum(
            1 for task_row in per_task_rows if _is_saturated_task_row(task_row)
        )
        if saturated_count == len(per_task_rows):
            warnings.append(
                "All shared tasks are saturated (both 1.0 or both 0.0) — zero discriminating signal."
            )

    config_arms = (
        (report.get("config_a", "A"), "summary_a"),
        (report.get("config_b", "B"), "summary_b"),
    )
    for config_label, summary_key in config_arms:
        config_summary = report.get(summary_key, {})
        completed_count = int(config_summary.get("completed", 0))
        infra_error_count = int(config_summary.get("infra_errors", 0))
        total_attempts = completed_count + infra_error_count
        if (
            total_attempts > 0
            and (infra_error_count / total_attempts) > HIGH_INFRA_ERROR_RATE_THRESHOLD
        ):
            warnings.append(
                f"High infra_error rate on {config_label} ({infra_error_count}/{total_attempts} > 10%): "
                "run `eval-retry` before trusting results."
            )
    return warnings


def _build_per_task_comparison_row(
    task_id: str,
    scores_a: list[float],
    scores_b: list[float],
    seed: int,
) -> tuple[dict[str, Any], float, bool, bool]:
    """Compute task-level mean scores, delta, paired CI, and majority-pass flags."""
    mean_a = float(np.mean(scores_a))
    mean_b = float(np.mean(scores_b))
    delta = mean_b - mean_a
    paired_trial_deltas = [score_b - score_a for score_a, score_b in zip(scores_a, scores_b)]
    task_ci_low, task_ci_high = paired_bootstrap_ci(paired_trial_deltas, seed=seed)

    row = {
        "task_id": task_id,
        "n_a": len(scores_a),
        "n_b": len(scores_b),
        "score_a": round(mean_a, 4),
        "score_b": round(mean_b, 4),
        "delta": round(delta, 4),
        "ci_95": [round(task_ci_low, 4), round(task_ci_high, 4)],
        "is_noise": (task_ci_low <= 0.0 <= task_ci_high),
    }
    return (
        row,
        delta,
        mean_a >= MAJORITY_PASS_SCORE_THRESHOLD,
        mean_b >= MAJORITY_PASS_SCORE_THRESHOLD,
    )


def compare_configs(
    trials_a: list[TrialResult],
    trials_b: list[TrialResult],
    name_a: str,
    name_b: str,
    seed: int = DEFAULT_RANDOM_SEED,
) -> dict[str, Any]:
    """Compare Config B against Config A over completed trials, paired at the task level."""
    by_task_a: dict[str, list[TrialResult]] = defaultdict(list)
    by_task_b: dict[str, list[TrialResult]] = defaultdict(list)
    for trial in trials_a:
        if trial.status == TrialStatus.COMPLETED and trial.score is not None:
            by_task_a[trial.task_id].append(trial)
    for trial in trials_b:
        if trial.status == TrialStatus.COMPLETED and trial.score is not None:
            by_task_b[trial.task_id].append(trial)

    shared_tasks = sorted(set(by_task_a.keys()) & set(by_task_b.keys()))
    per_task_rows: list[dict[str, Any]] = []
    task_deltas: list[float] = []
    majority_pass_a: list[bool] = []
    majority_pass_b: list[bool] = []

    for task_id in shared_tasks:
        scores_a = [float(trial.score) for trial in by_task_a[task_id] if trial.score is not None]
        scores_b = [float(trial.score) for trial in by_task_b[task_id] if trial.score is not None]
        row, delta, pass_a, pass_b = _build_per_task_comparison_row(
            task_id, scores_a, scores_b, seed
        )
        per_task_rows.append(row)
        task_deltas.append(delta)
        majority_pass_a.append(pass_a)
        majority_pass_b.append(pass_b)

    delta_mean = round(float(np.mean(task_deltas)), 4) if task_deltas else 0.0
    ci_low, ci_high = paired_bootstrap_ci(task_deltas, seed=seed)
    mcnemar_p = exact_mcnemar_pvalue(majority_pass_a, majority_pass_b)
    is_noise = ci_low <= 0.0 <= ci_high

    if is_noise:
        verdict = "NOISE"
    elif delta_mean > 0:
        verdict = f"{name_b} BETTER"
    else:
        verdict = f"{name_a} BETTER"

    report: dict[str, Any] = {
        "config_a": name_a,
        "config_b": name_b,
        "shared_tasks": len(shared_tasks),
        "summary_a": summarize_config(trials_a),
        "summary_b": summarize_config(trials_b),
        "delta_mean": delta_mean,
        "ci_95": [round(ci_low, 4), round(ci_high, 4)],
        "mcnemar_p": round(mcnemar_p, 4),
        "verdict": verdict,
        "per_task": per_task_rows,
    }
    report["warnings"] = power_warnings(report)
    return report
