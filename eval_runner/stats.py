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
            "cost_per_pass_usd": None,
            "avg_runtime_sec": 0.0,
            "p50_runtime_sec": 0.0,
            "p95_runtime_sec": 0.0,
            "avg_tokens": 0,
        }
    runtimes = np.array([t.runtime_sec for t in completed], dtype=float)
    total_cost = float(np.sum([t.cost_usd for t in completed]))
    n_passed = sum(1 for t in completed if t.passed)
    return {
        "completed": len(completed),
        "infra_errors": len(errored),
        "mean_score": round(float(np.mean([t.score for t in completed if t.score is not None])), 4),
        "pass_rate": round(float(n_passed / len(completed)), 4),
        "avg_cost_usd": round(float(np.mean([t.cost_usd for t in completed])), 6),
        "total_cost_usd": round(total_cost, 6),
        "cost_per_pass_usd": round(total_cost / n_passed, 6) if n_passed else None,
        "avg_runtime_sec": round(float(np.mean(runtimes)), 2),
        "p50_runtime_sec": round(float(np.percentile(runtimes, 50)), 2),
        "p95_runtime_sec": round(float(np.percentile(runtimes, 95)), 2),
        "avg_tokens": int(np.mean([t.input_tokens + t.output_tokens for t in completed])),
    }


def power_warnings(report: dict[str, Any]) -> list[str]:
    """Flag under-powered or biased comparisons so small-sample noise isn't over-interpreted."""
    warnings: list[str] = []
    shared = int(report.get("shared_tasks", 0))
    if shared < 10:
        warnings.append(
            f"Low task count ({shared} shared task(s) < 10): paired bootstrap CI has wide uncertainty."
        )
    per_task = report.get("per_task", [])
    if per_task:
        min_n = min(min(r["n_a"], r["n_b"]) for r in per_task)
        if min_n < 3:
            warnings.append(
                f"Low trial count per task (min n={min_n} < 3): single-trial variance may dominate."
            )
        saturated = sum(
            1 for r in per_task if (r["score_a"] >= 0.999 and r["score_b"] >= 0.999) or (r["score_a"] <= 0.001 and r["score_b"] <= 0.001)
        )
        if saturated == len(per_task):
            warnings.append("All shared tasks are saturated (both 1.0 or both 0.0) — zero discriminating signal.")
    for label, key in ((report.get("config_a", "A"), "summary_a"), (report.get("config_b", "B"), "summary_b")):
        s = report.get(key, {})
        total = int(s.get("completed", 0)) + int(s.get("infra_errors", 0))
        if total > 0 and (int(s.get("infra_errors", 0)) / total) > 0.10:
            warnings.append(
                f"High infra_error rate on {label} ({s['infra_errors']}/{total} > 10%): run `eval-retry` before trusting results."
            )
    return warnings


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
        scores_a = [float(t.score) for t in by_task_a[task_id] if t.score is not None]
        scores_b = [float(t.score) for t in by_task_b[task_id] if t.score is not None]
        mean_a = float(np.mean(scores_a))
        mean_b = float(np.mean(scores_b))
        delta = mean_b - mean_a
        deltas.append(delta)
        maj_a.append(mean_a >= 0.5)
        maj_b.append(mean_b >= 0.5)

        paired_trials = [b - a for a, b in zip(scores_a, scores_b)]
        t_ci_low, t_ci_high = paired_bootstrap_ci(paired_trials, seed=seed)
        per_task.append(
            {
                "task_id": task_id,
                "n_a": len(scores_a),
                "n_b": len(scores_b),
                "score_a": round(mean_a, 4),
                "score_b": round(mean_b, 4),
                "delta": round(delta, 4),
                "ci_95": [round(t_ci_low, 4), round(t_ci_high, 4)],
                "is_noise": (t_ci_low <= 0.0 <= t_ci_high),
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

    report = {
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
    report["warnings"] = power_warnings(report)
    return report
