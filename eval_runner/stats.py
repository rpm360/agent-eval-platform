"""Statistical comparison: paired bootstrap 95% CI, exact McNemar test, per-task deltas."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import numpy as np
from scipy.stats import binomtest, bootstrap

from eval_runner.schemas import TrialResult


def exact_mcnemar_pvalue(a_pass: list[bool], b_pass: list[bool]) -> float:
    """Two-sided exact binomial McNemar test on paired pass/fail outcomes."""
    b_only = sum(1 for a, b in zip(a_pass, b_pass) if (not a) and b)
    a_only = sum(1 for a, b in zip(a_pass, b_pass) if a and (not b))
    discordant = a_only + b_only
    if discordant == 0:
        return 1.0
    return float(binomtest(min(a_only, b_only), discordant, 0.5, alternative="two-sided").pvalue)


def paired_bootstrap_ci(
    deltas: list[float],
    confidence_level: float = 0.95,
    n_resamples: int = 10_000,
    seed: int = 42,
) -> tuple[float, float]:
    """Paired bootstrap CI for the mean of per-task deltas (B - A)."""
    arr = np.asarray(deltas, dtype=float)
    if arr.size == 0:
        return (0.0, 0.0)
    if arr.size == 1 or np.allclose(arr, arr[0]):
        val = float(arr[0])
        return (val, val)
    rng = np.random.default_rng(seed)
    res = bootstrap(
        (arr,),
        np.mean,
        confidence_level=confidence_level,
        n_resamples=n_resamples,
        method="percentile",
        random_state=rng,
    )
    return (float(res.confidence_interval.low), float(res.confidence_interval.high))


def summarize_config(trials: list[TrialResult]) -> dict[str, Any]:
    completed = [t for t in trials if t.status == "completed" and t.score is not None]
    errored = [t for t in trials if t.status == "infra_error"]
    if not completed:
        return {
            "completed": 0,
            "infra_errors": len(errored),
            "mean_score": 0.0,
            "pass_rate": 0.0,
            "avg_cost_usd": 0.0,
            "total_cost_usd": 0.0,
            "avg_runtime_sec": 0.0,
            "avg_tokens": 0,
        }
    return {
        "completed": len(completed),
        "infra_errors": len(errored),
        "mean_score": round(float(np.mean([t.score for t in completed if t.score is not None])), 4),
        "pass_rate": round(float(np.mean([1.0 if t.passed else 0.0 for t in completed])), 4),
        "avg_cost_usd": round(float(np.mean([t.cost_usd for t in completed])), 6),
        "total_cost_usd": round(float(np.sum([t.cost_usd for t in completed])), 6),
        "avg_runtime_sec": round(float(np.mean([t.runtime_sec for t in completed])), 2),
        "avg_tokens": int(np.mean([t.input_tokens + t.output_tokens for t in completed])),
    }


def compare_configs(
    trials_a: list[TrialResult],
    trials_b: list[TrialResult],
    name_a: str,
    name_b: str,
    seed: int = 42,
) -> dict[str, Any]:
    """Compare Config B against Config A over completed trials, paired at the task level."""
    comp_a = [t for t in trials_a if t.status == "completed" and t.score is not None]
    comp_b = [t for t in trials_b if t.status == "completed" and t.score is not None]

    by_task_a: dict[str, list[TrialResult]] = defaultdict(list)
    by_task_b: dict[str, list[TrialResult]] = defaultdict(list)
    for t in comp_a:
        by_task_a[t.task_id].append(t)
    for t in comp_b:
        by_task_b[t.task_id].append(t)

    shared_tasks = sorted(set(by_task_a.keys()) & set(by_task_b.keys()))
    per_task: list[dict[str, Any]] = []
    deltas: list[float] = []
    maj_a: list[bool] = []
    maj_b: list[bool] = []

    for task_id in shared_tasks:
        mean_a = float(np.mean([t.score for t in by_task_a[task_id] if t.score is not None]))
        mean_b = float(np.mean([t.score for t in by_task_b[task_id] if t.score is not None]))
        delta = mean_b - mean_a
        deltas.append(delta)
        maj_a.append(mean_a >= 0.5)
        maj_b.append(mean_b >= 0.5)
        per_task.append(
            {
                "task_id": task_id,
                "n_a": len(by_task_a[task_id]),
                "n_b": len(by_task_b[task_id]),
                "score_a": round(mean_a, 4),
                "score_b": round(mean_b, 4),
                "delta": round(delta, 4),
            }
        )

    delta_mean = round(float(np.mean(deltas)), 4) if deltas else 0.0
    ci_low, ci_high = paired_bootstrap_ci(deltas, seed=seed)
    mcnemar_p = exact_mcnemar_pvalue(maj_a, maj_b)
    is_noise = ci_low <= 0.0 <= ci_high

    if is_noise:
        verdict = "NOISE"
    elif delta_mean > 0:
        verdict = f"{name_b} BETTER"
    else:
        verdict = f"{name_a} BETTER"

    return {
        "config_a": name_a,
        "config_b": name_b,
        "shared_tasks": len(shared_tasks),
        "summary_a": summarize_config(trials_a),
        "summary_b": summarize_config(trials_b),
        "delta_mean": delta_mean,
        "ci_95": [round(ci_low, 4), round(ci_high, 4)],
        "mcnemar_p": round(mcnemar_p, 4),
        "verdict": verdict,
        "per_task": per_task,
    }
