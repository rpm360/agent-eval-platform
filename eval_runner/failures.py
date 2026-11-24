"""Rule-based failure taxonomy for failed evaluation trials."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from typing import Any

from eval_runner.constants import (
    BORDERLINE_SCORE_MARGIN,
    GraderType,
    LOOP_CONSECUTIVE_CALL_THRESHOLD,
    MAX_FAILURE_EXAMPLES_PER_CATEGORY,
    TrialStatus,
)
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

STEP_EXHAUSTION_ERROR_MARKERS: tuple[str, ...] = (
    "recursion_limit",
    "recursion limit",
    "max_iterations",
    "iteration limit",
)

HALLUCINATED_TOOL_ARG_PATTERNS: tuple[str, ...] = (
    "file not found",
    "directory not found",
    "no such file",
    "invalid argument",
    "jsondecodeerror",
    "unknown skill",
)

UNKNOWN_TOOL_OUTPUT_PATTERNS: tuple[str, ...] = (
    "unknown tool",
    "not a valid tool",
)

REFUSAL_PHRASES: tuple[str, ...] = (
    "i cannot",
    "i can't",
    "unable to",
    "not possible",
    "i do not have access",
)


def _normalize_tool_args(raw_args: Any) -> str:
    if isinstance(raw_args, str):
        return raw_args.strip()
    try:
        return json.dumps(raw_args, sort_keys=True)
    except TypeError:
        return str(raw_args)


def _exceeded_step_limit(trial: TrialResult, events: list[TraceEvent], settings: Settings) -> bool:
    if trial.steps >= settings.max_steps:
        return True
    combined_errors = " ".join(
        str(event.payload.get("message", "")) for event in events if event.type == "error"
    ).lower()
    return any(marker in combined_errors for marker in STEP_EXHAUSTION_ERROR_MARKERS)


def _has_consecutive_tool_loop(tool_calls: list[TraceEvent]) -> bool:
    """Return True when `>= 3` consecutive `(tool_name, args)` calls are identical."""
    streak = 0
    previous_signature: tuple[str, str] | None = None
    for event in tool_calls:
        signature = (
            str(event.payload.get("name", "")),
            _normalize_tool_args(event.payload.get("args", "")),
        )
        streak = streak + 1 if signature == previous_signature else 1
        previous_signature = signature
        if streak >= LOOP_CONSECUTIVE_CALL_THRESHOLD:
            return True
    return False


def _has_hallucinated_tool_args(tool_results: list[TraceEvent]) -> bool:
    for event in tool_results:
        lowered_output = str(event.payload.get("output", "")).lower()
        if any(pattern in lowered_output for pattern in HALLUCINATED_TOOL_ARG_PATTERNS):
            return True
    return False


def _used_disallowed_or_unknown_tool(
    tool_calls: list[TraceEvent],
    tool_results: list[TraceEvent],
    allowed_tools: list[str] | None,
) -> bool:
    if allowed_tools is not None:
        allowed_set = set(allowed_tools)
        if any(str(event.payload.get("name", "")) not in allowed_set for event in tool_calls):
            return True
    for event in tool_results:
        lowered_output = str(event.payload.get("output", "")).lower()
        if any(pattern in lowered_output for pattern in UNKNOWN_TOOL_OUTPUT_PATTERNS):
            return True
    return False


def _missed_required_memory(task: TaskSpec, events: list[TraceEvent]) -> bool:
    if "memory" not in task.discriminates and task.category != "memory":
        return False
    return not any(
        event.type == "memory_op" and event.payload.get("op") == "read" for event in events
    )


def _missed_required_skill(task: TaskSpec, events: list[TraceEvent]) -> bool:
    if "skills" not in task.discriminates and task.category != "skill":
        return False
    return not any(event.type == "skill_invoked" for event in events)


def _gave_up_early(final_answer: str, tool_calls: list[TraceEvent]) -> bool:
    if not tool_calls:
        return True
    lowered_answer = final_answer.lower()
    return any(phrase in lowered_answer for phrase in REFUSAL_PHRASES)


def _is_borderline_judge_failure(trial: TrialResult, task: TaskSpec) -> bool:
    if trial.grade is None or trial.grade.grader_type != GraderType.LLM_JUDGE:
        return False
    return abs(trial.grade.score - task.grader.pass_threshold) <= BORDERLINE_SCORE_MARGIN


def classify_failure(
    trial: TrialResult,
    events: list[TraceEvent],
    task: TaskSpec,
    settings: Settings,
) -> str | None:
    """Classify why a trial failed into a deterministic priority-ordered category (`None` on pass)."""
    if trial.status == TrialStatus.INFRA_ERROR:
        return TrialStatus.INFRA_ERROR
    if trial.passed:
        return None

    total_tokens = trial.input_tokens + trial.output_tokens
    if settings.max_total_tokens is not None and total_tokens > settings.max_total_tokens:
        return "budget_exhausted"

    grader_reasoning = (trial.grade.reasoning if trial.grade else "") or ""
    if "timed out" in grader_reasoning.lower():
        return "timeout"

    if _exceeded_step_limit(trial, events, settings):
        return "step_exhaustion"

    tool_calls = [event for event in events if event.type == "tool_call"]
    if _has_consecutive_tool_loop(tool_calls):
        return "loop"

    tool_results = [event for event in events if event.type == "tool_result"]
    if _has_hallucinated_tool_args(tool_results):
        return "hallucinated_tool_args"

    if _used_disallowed_or_unknown_tool(tool_calls, tool_results, settings.tools):
        return "wrong_tool"

    if _missed_required_memory(task, events):
        return "missed_memory"

    if _missed_required_skill(task, events):
        return "missed_skill"

    if _gave_up_early(trial.final_answer or "", tool_calls):
        return "gave_up_early"

    if _is_borderline_judge_failure(trial, task):
        return "grader_borderline"

    return "wrong_output"


def summarize_failures(trials: list[TrialResult]) -> dict[str, dict[str, Any]]:
    """Group failed and `infra_error` trials by `config_name` with category counts and examples."""
    trials_by_config: dict[str, list[TrialResult]] = defaultdict(list)
    for trial in trials:
        trials_by_config[trial.config_name].append(trial)

    failure_summary: dict[str, dict[str, Any]] = {}
    for config_name, config_trials in sorted(trials_by_config.items()):
        category_counts: Counter[str] = Counter()
        category_examples: dict[str, list[str]] = defaultdict(list)
        failed_count = 0

        for trial in config_trials:
            if trial.status == TrialStatus.INFRA_ERROR:
                category = trial.failure_category or str(TrialStatus.INFRA_ERROR)
            elif trial.passed:
                continue
            else:
                category = trial.failure_category or "wrong_output"

            failed_count += 1
            category_counts[category] += 1
            if len(category_examples[category]) < MAX_FAILURE_EXAMPLES_PER_CATEGORY:
                category_examples[category].append(trial.trial_id)

        failure_summary[config_name] = {
            "total": len(config_trials),
            "failed": failed_count,
            "categories": dict(category_counts.most_common()),
            "examples": dict(category_examples),
        }
    return failure_summary


def compare_failures(
    trials_a: list[TrialResult],
    trials_b: list[TrialResult],
    name_a: str,
    name_b: str,
) -> list[dict[str, Any]]:
    """Return per-category failure count deltas (`B - A`) sorted by largest magnitude change."""
    categories_a = summarize_failures(trials_a).get(name_a, {}).get("categories", {})
    categories_b = summarize_failures(trials_b).get(name_b, {}).get("categories", {})
    all_categories = sorted(set(categories_a) | set(categories_b))

    delta_rows = [
        {
            "category": category,
            "count_a": categories_a.get(category, 0),
            "count_b": categories_b.get(category, 0),
            "delta": categories_b.get(category, 0) - categories_a.get(category, 0),
        }
        for category in all_categories
    ]
    delta_rows.sort(key=lambda row: (-abs(row["delta"]), row["category"]))
    return delta_rows
