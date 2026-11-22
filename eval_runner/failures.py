"""Rule-based failure taxonomy for failed evaluation trials."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from typing import Any

from eval_runner.schemas import Settings, TaskSpec, TraceEvent, TrialResult

FAILURE_CATEGORIES = (
    "infra_error",
    "budget_exhausted",
    "timeout",
    "step_exhaustion",
    "loop",
    "hallucinated_tool_args",
    "wrong_tool",
    "missed_memory",
    "missed_skill",
    "gave_up_early",
    "grader_borderline",
    "wrong_output",
)


def _norm_args(raw_args: Any) -> str:
    if isinstance(raw_args, str):
        return raw_args.strip()
    try:
        return json.dumps(raw_args, sort_keys=True)
    except Exception:
        return str(raw_args)


def classify_failure(
    trial: TrialResult,
    events: list[TraceEvent],
    task: TaskSpec,
    settings: Settings,
) -> str | None:
    """Classify why a trial failed into a deterministic category (None for passed trials)."""
    if trial.status == "infra_error":
        return "infra_error"
    if trial.passed:
        return None

    total_tokens = trial.input_tokens + trial.output_tokens
    if settings.max_total_tokens is not None and total_tokens > settings.max_total_tokens:
        return "budget_exhausted"

    reasoning = (trial.grade.reasoning if trial.grade else "") or ""
    if "timed out" in reasoning.lower():
        return "timeout"

    error_msgs = " ".join(
        str(ev.payload.get("message", ""))
        for ev in events
        if ev.type == "error"
    ).lower()
    if (
        trial.steps >= settings.max_steps
        or "recursion_limit" in error_msgs
        or "recursion limit" in error_msgs
        or "max_iterations" in error_msgs
        or "iteration limit" in error_msgs
    ):
        return "step_exhaustion"

    tool_calls = [ev for ev in events if ev.type == "tool_call"]
    # 3+ identical consecutive (tool_name, args) calls
    streak = 0
    prev_sig: tuple[str, str] | None = None
    for ev in tool_calls:
        sig = (str(ev.payload.get("name", "")), _norm_args(ev.payload.get("args", "")))
        streak = streak + 1 if sig == prev_sig else 1
        prev_sig = sig
        if streak >= 3:
            return "loop"

    tool_results = [ev for ev in events if ev.type == "tool_result"]
    for ev in tool_results:
        out = str(ev.payload.get("output", "")).lower()
        if any(
            pat in out
            for pat in (
                "file not found",
                "directory not found",
                "no such file",
                "invalid argument",
                "jsondecodeerror",
                "unknown skill",
            )
        ):
            return "hallucinated_tool_args"

    if settings.tools is not None:
        allowed = set(settings.tools)
        for ev in tool_calls:
            if str(ev.payload.get("name", "")) not in allowed:
                return "wrong_tool"
    for ev in tool_results:
        out = str(ev.payload.get("output", "")).lower()
        if "unknown tool" in out or "not a valid tool" in out:
            return "wrong_tool"

    if "memory" in task.discriminates or task.category == "memory":
        has_mem_read = any(
            ev.type == "memory_op" and ev.payload.get("op") == "read"
            for ev in events
        )
        if not has_mem_read:
            return "missed_memory"

    if "skills" in task.discriminates or task.category == "skill":
        has_skill = any(ev.type == "skill_invoked" for ev in events)
        if not has_skill:
            return "missed_skill"

    ans_low = (trial.final_answer or "").lower()
    if not tool_calls or any(
        phrase in ans_low
        for phrase in ("i cannot", "i can't", "unable to", "not possible", "i do not have access")
    ):
        return "gave_up_early"

    if (
        trial.grade is not None
        and trial.grade.grader_type == "llm_judge"
        and abs(trial.grade.score - task.grader.pass_threshold) <= 0.1
    ):
        return "grader_borderline"

    return "wrong_output"


def summarize_failures(trials: list[TrialResult]) -> dict[str, dict[str, Any]]:
    """Group failed/infra trials by config_name -> category counts + example trial IDs."""
    by_cfg: dict[str, list[TrialResult]] = defaultdict(list)
    for t in trials:
        by_cfg[t.config_name].append(t)

    summary: dict[str, dict[str, Any]] = {}
    for cfg_name, cfg_trials in sorted(by_cfg.items()):
        counts: Counter[str] = Counter()
        examples: dict[str, list[str]] = defaultdict(list)
        failed = 0
        for t in cfg_trials:
            if t.status == "infra_error":
                cat = t.failure_category or "infra_error"
            elif t.passed:
                continue
            else:
                cat = t.failure_category or "wrong_output"
            failed += 1
            counts[cat] += 1
            if len(examples[cat]) < 3:
                examples[cat].append(t.trial_id)
        summary[cfg_name] = {
            "total": len(cfg_trials),
            "failed": failed,
            "categories": dict(counts.most_common()),
            "examples": dict(examples),
        }
    return summary


def compare_failures(
    trials_a: list[TrialResult],
    trials_b: list[TrialResult],
    name_a: str,
    name_b: str,
) -> list[dict[str, Any]]:
    """Return per-category failure deltas (B - A) sorted by largest regression."""
    sum_a = summarize_failures(trials_a).get(name_a, {}).get("categories", {})
    sum_b = summarize_failures(trials_b).get(name_b, {}).get("categories", {})
    cats = sorted(set(sum_a) | set(sum_b))
    rows = [
        {
            "category": cat,
            "count_a": sum_a.get(cat, 0),
            "count_b": sum_b.get(cat, 0),
            "delta": sum_b.get(cat, 0) - sum_a.get(cat, 0),
        }
        for cat in cats
    ]
    rows.sort(key=lambda r: (-abs(r["delta"]), r["category"]))
    return rows
