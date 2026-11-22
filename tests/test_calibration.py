"""Tests for judge calibration: Cohen's kappa math, label set validation, and trust gate."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from eval_runner.calibration import cohens_kappa, load_calibration_labels, run_calibration
from eval_runner.schemas import TaskSpec


def test_cohens_kappa_known_values() -> None:
    assert cohens_kappa([True, True, False, False], [True, True, False, False]) == pytest.approx(1.0)
    assert cohens_kappa([True, False, True, False], [True, True, False, False]) == pytest.approx(0.0)
    # 7/10 agreement with 50/50 marginals -> kappa = (0.7 - 0.5) / 0.5 = 0.4
    y_true = [True] * 5 + [False] * 5
    y_pred = [True, True, True, True, False, False, False, False, True, True]
    assert cohens_kappa(y_true, y_pred) == pytest.approx(0.375, abs=0.05)


def test_calibration_labels_cover_all_judge_tasks() -> None:
    examples = load_calibration_labels(Path("calibration/judge_labels.jsonl"))
    assert len(examples) == 30
    judge_tasks = {
        d.name for d in Path("tasks").iterdir()
        if d.is_dir() and TaskSpec.from_dir(d).grader.type == "llm_judge"
    }
    assert {ex.task_id for ex in examples} == judge_tasks


def test_run_calibration_trusted_and_untrusted_gates(tmp_path: Path) -> None:
    # Trusted when mocked judge agrees with human labels
    def fake_call_match(model, messages, temperature=0.0, **kwargs):
        user_msg = messages[-1]["content"]
        # Match by unique snippet: pass examples contain human-aligned pass text
        ok = "Off-by-one" in user_msg or "Last" in user_msg or "pool" in user_msg
        return f'{{"score": {1.0 if ok else 0.0}, "passed": {str(ok).lower()}, "reasoning": "ok"}}', 10, 5

    # Exact-match mock keyed off calibration examples
    examples = load_calibration_labels(Path("calibration/judge_labels.jsonl"))
    by_snippet = {next(iter(ex.artifacts.values()))[:40]: (ex.human_passed, ex.human_score) for ex in examples}

    def exact_match_judge(model, messages, temperature=0.0, **kwargs):
        body = messages[-1]["content"]
        for snip, (hp, hs) in by_snippet.items():
            if snip in body:
                return f'{{"score": {hs}, "passed": {str(hp).lower()}, "reasoning": "matched"}}', 10, 5
        return '{"score": 0.0, "passed": false, "reasoning": "miss"}', 10, 5

    with patch("eval_runner.graders.call_model_with_retry", side_effect=exact_match_judge):
        rep = run_calibration(judge_model_id="gemini-flash", repeats=2, out_dir=tmp_path)
    assert rep["verdict"] == "TRUSTED"
    assert rep["cohens_kappa"] == 1.0
    assert rep["accuracy"] == 1.0
    assert rep["self_agreement"] == 1.0

    # Untrusted when judge always says pass=true
    def always_pass(model, messages, temperature=0.0, **kwargs):
        return '{"score": 1.0, "passed": true, "reasoning": "rubber stamp"}', 10, 5

    with patch("eval_runner.graders.call_model_with_retry", side_effect=always_pass):
        bad = run_calibration(judge_model_id="gemini-flash", repeats=1, out_dir=tmp_path)
    assert bad["verdict"] == "UNTRUSTED"
    assert bad["cohens_kappa"] == 0.0
    assert len(bad["disagreements"]) == 15
