"""Tests for the rule-based failure taxonomy classifier and summary."""

from __future__ import annotations

from eval_runner.failures import classify_failure, compare_failures, summarize_failures
from eval_runner.schemas import GradeResult, GraderSpec, Settings, TaskSpec, TraceEvent, TrialResult


def _trial(**kw) -> TrialResult:
    defaults = dict(
        trial_id="t1",
        experiment_id="e1",
        config_name="cfg_a",
        config_hash="abc",
        harness="langgraph",
        model="gemini-flash",
        task_id="code-fix-lru-cache",
        trial_index=1,
        status="completed",
        score=0.0,
        passed=False,
        steps=2,
        final_answer="Done.",
        grade=GradeResult(grader_type="deterministic", score=0.0, passed=False, reasoning="exit 1"),
    )
    defaults.update(kw)
    return TrialResult(**defaults)


def _task(**kw) -> TaskSpec:
    defaults = dict(id="code-fix-lru-cache", category="coding", discriminates=["coding"])
    defaults.update(kw)
    return TaskSpec(**defaults)


def test_classify_failure_categories() -> None:
    settings = Settings(max_steps=10, max_total_tokens=1000)

    assert classify_failure(_trial(passed=True, score=1.0), [], _task(), settings) is None
    assert classify_failure(_trial(status="infra_error"), [], _task(), settings) == "infra_error"
    assert classify_failure(_trial(input_tokens=800, output_tokens=300), [], _task(), settings) == "budget_exhausted"
    assert (
        classify_failure(
            _trial(grade=GradeResult(grader_type="deterministic", score=0.0, passed=False, reasoning="Agent timed out after 120s.")),
            [],
            _task(),
            settings,
        )
        == "timeout"
    )
    assert classify_failure(_trial(steps=10), [], _task(), settings) == "step_exhaustion"

    loop_events = [
        TraceEvent(seq=1, type="tool_call", payload={"name": "read_file", "args": {"path": "a.py"}}),
        TraceEvent(seq=2, type="tool_call", payload={"name": "read_file", "args": {"path": "a.py"}}),
        TraceEvent(seq=3, type="tool_call", payload={"name": "read_file", "args": {"path": "a.py"}}),
    ]
    assert classify_failure(_trial(), loop_events, _task(), settings) == "loop"

    hal_events = [
        TraceEvent(seq=1, type="tool_call", payload={"name": "read_file", "args": {"path": "nope.py"}}),
        TraceEvent(seq=2, type="tool_result", payload={"output": "error: file not found: nope.py"}),
    ]
    assert classify_failure(_trial(), hal_events, _task(), settings) == "hallucinated_tool_args"

    mem_task = _task(id="mem-deploy-convention", category="memory", discriminates=["memory"])
    ok_tool = [TraceEvent(seq=1, type="tool_call", payload={"name": "write_file", "args": {}})]
    assert classify_failure(_trial(), ok_tool, mem_task, settings) == "missed_memory"

    skill_task = _task(id="skill-release-tag", category="skill", discriminates=["skills"])
    assert classify_failure(_trial(), ok_tool, skill_task, settings) == "missed_skill"

    assert classify_failure(_trial(final_answer="I cannot access that."), ok_tool, _task(), settings) == "gave_up_early"

    judge_task = _task(grader=GraderSpec(type="llm_judge", pass_threshold=0.7))
    borderline = _trial(grade=GradeResult(grader_type="llm_judge", score=0.65, passed=False))
    assert classify_failure(borderline, ok_tool, judge_task, settings) == "grader_borderline"

    assert classify_failure(_trial(), ok_tool, _task(), settings) == "wrong_output"


def test_summarize_and_compare_failures() -> None:
    a = [_trial(config_name="a", failure_category="missed_memory"), _trial(config_name="a", passed=True, score=1.0)]
    b = [_trial(config_name="b", failure_category="missed_memory"), _trial(config_name="b", failure_category="wrong_output")]
    s = summarize_failures(a + b)
    assert s["a"]["failed"] == 1
    assert s["b"]["failed"] == 2
    deltas = compare_failures(a, b, "a", "b")
    assert any(r["category"] == "wrong_output" and r["delta"] == 1 for r in deltas)
