"""LLM-as-judge calibration against human-labelled examples (Cohen's kappa, accuracy, consistency)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import BaseModel, Field
from scipy.stats import spearmanr

from eval_runner.constants import (
    CalibrationVerdict,
    DEFAULT_CALIBRATION_REPEATS,
    DEFAULT_JUDGE_MODEL_ID,
)
from eval_runner.graders import grade_llm_judge
from eval_runner.models import load_models_catalog, resolve_model
from eval_runner.schemas import ModelCatalog, ModelEntry, TaskSpec

logger = logging.getLogger(__name__)

KAPPA_THRESHOLD = 0.6
ACCURACY_THRESHOLD = 0.8


class CalibrationExample(BaseModel):
    """Human-labelled ground-truth grading example from `calibration/judge_labels.jsonl`."""

    id: str
    task_id: str
    artifacts: dict[str, str] = Field(default_factory=dict)
    final_answer: str = ""
    human_passed: bool
    human_score: float = Field(ge=0.0, le=1.0)
    labeler: str = "human"
    notes: str = ""


def load_calibration_labels(
    path: Path = Path("calibration/judge_labels.jsonl"),
) -> list[CalibrationExample]:
    """Load and validate all JSONL human calibration examples from `path`."""
    return [
        CalibrationExample.model_validate_json(raw_line.strip())
        for raw_line in path.read_text(encoding="utf-8").splitlines()
        if raw_line.strip()
    ]


def _confusion_counts(y_true: list[bool], y_pred: list[bool]) -> tuple[int, int, int, int]:
    tp = sum(1 for truth, pred in zip(y_true, y_pred) if truth and pred)
    tn = sum(1 for truth, pred in zip(y_true, y_pred) if (not truth) and (not pred))
    fp = sum(1 for truth, pred in zip(y_true, y_pred) if (not truth) and pred)
    fn = sum(1 for truth, pred in zip(y_true, y_pred) if truth and (not pred))
    return tp, tn, fp, fn


def cohens_kappa(y_true: list[bool], y_pred: list[bool]) -> float:
    """Compute Cohen's kappa agreement coefficient for binary pass/fail labels."""
    if len(y_true) != len(y_pred) or not y_true:
        return 0.0
    total = len(y_true)
    tp, tn, fp, fn = _confusion_counts(y_true, y_pred)

    observed_agreement = (tp + tn) / total
    expected_agreement = (((tp + fp) * (tp + fn)) + ((fn + tn) * (fp + tn))) / (total * total)
    if expected_agreement >= 1.0:
        return 1.0 if observed_agreement == 1.0 else 0.0
    return (observed_agreement - expected_agreement) / (1.0 - expected_agreement)


def _resolve_calibration_judge(catalog: ModelCatalog, judge_model_id: str) -> ModelEntry:
    try:
        return resolve_model(catalog, judge_model_id)
    except KeyError:
        if "/" in judge_model_id or not catalog.models:
            raise
        fallback_id = next(
            (entry.id for entry in catalog.models if entry.provider != "mock"),
            catalog.models[0].id,
        )
        return resolve_model(catalog, fallback_id)


def _load_calibration_tasks(
    examples: list[CalibrationExample],
    tasks_root: Path,
    judge_model_id: str,
) -> dict[str, tuple[TaskSpec, str]]:
    """Preload and pin `judge_model` on every unique `TaskSpec` referenced by `examples`."""
    task_cache: dict[str, tuple[TaskSpec, str]] = {}
    for example in examples:
        if example.task_id in task_cache:
            continue
        task_dir = tasks_root / example.task_id
        task_spec = TaskSpec.from_dir(task_dir)
        pinned_task = task_spec.model_copy(
            update={"grader": task_spec.grader.model_copy(update={"judge_model": judge_model_id})}
        )
        instruction = (task_dir / "instruction.md").read_text(encoding="utf-8").strip()
        task_cache[example.task_id] = (pinned_task, instruction)
    return task_cache


def _evaluate_example_repeats(
    *,
    example: CalibrationExample,
    task: TaskSpec,
    instruction: str,
    catalog: ModelCatalog,
    repeats: int,
) -> tuple[bool, float, bool, str]:
    """Grade one calibration example `repeats` times, returning `(majority_pass, mean_score, is_consistent, last_reasoning)`."""
    repeat_passes: list[bool] = []
    repeat_scores: list[float] = []
    last_reasoning = ""
    for _ in range(max(1, repeats)):
        grade_result = grade_llm_judge(
            task=task,
            instruction=instruction,
            final_answer=example.final_answer,
            catalog=catalog,
            artifacts_content=example.artifacts,
        )
        repeat_passes.append(bool(grade_result.passed))
        repeat_scores.append(float(grade_result.score))
        last_reasoning = grade_result.reasoning

    is_self_consistent = len(set(repeat_passes)) == 1
    majority_pass = sum(1 for passed in repeat_passes if passed) > (len(repeat_passes) / 2.0)
    mean_score = float(np.mean(repeat_scores))
    return majority_pass, mean_score, is_self_consistent, last_reasoning


def _compute_spearman_rho(human_scores: list[float], judge_scores: list[float]) -> float:
    if len(human_scores) < 2 or len(set(human_scores)) <= 1 or len(set(judge_scores)) <= 1:
        return 0.0
    rho_statistic = float(spearmanr(human_scores, judge_scores).statistic)
    return 0.0 if np.isnan(rho_statistic) else rho_statistic


def run_calibration(
    *,
    judge_model_id: str = DEFAULT_JUDGE_MODEL_ID,
    labels_path: Path = Path("calibration/judge_labels.jsonl"),
    tasks_root: Path = Path("tasks"),
    repeats: int = DEFAULT_CALIBRATION_REPEATS,
    models_path: Path = Path("models.yaml"),
    out_dir: Path = Path("results/calibration"),
) -> dict[str, Any]:
    """Run the LLM judge over human-labelled examples and compute agreement & trust verdict."""
    catalog = load_models_catalog(models_path) if models_path.exists() else ModelCatalog(models=[])
    judge_model = _resolve_calibration_judge(catalog, judge_model_id)
    examples = load_calibration_labels(labels_path)
    task_cache = _load_calibration_tasks(examples, tasks_root, judge_model.id)

    y_true: list[bool] = []
    y_pred: list[bool] = []
    human_scores: list[float] = []
    judge_scores: list[float] = []
    self_consistent_count = 0
    disagreements: list[dict[str, Any]] = []

    for example in examples:
        task, instruction = task_cache[example.task_id]
        majority_pass, mean_score, is_consistent, last_reasoning = _evaluate_example_repeats(
            example=example,
            task=task,
            instruction=instruction,
            catalog=catalog,
            repeats=repeats,
        )
        if is_consistent:
            self_consistent_count += 1

        y_true.append(example.human_passed)
        y_pred.append(majority_pass)
        human_scores.append(example.human_score)
        judge_scores.append(mean_score)

        if majority_pass != example.human_passed:
            disagreements.append(
                {
                    "id": example.id,
                    "task_id": example.task_id,
                    "human_passed": example.human_passed,
                    "human_score": example.human_score,
                    "judge_passed": majority_pass,
                    "judge_score": round(mean_score, 3),
                    "notes": example.notes,
                    "judge_reasoning": last_reasoning,
                }
            )

    n_examples = len(examples)
    tp, tn, fp, fn = _confusion_counts(y_true, y_pred)
    accuracy = (tp + tn) / n_examples if n_examples else 0.0
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    kappa = cohens_kappa(y_true, y_pred)
    score_mae = (
        float(np.mean(np.abs(np.array(judge_scores) - np.array(human_scores))))
        if n_examples
        else 0.0
    )
    spearman_rho = _compute_spearman_rho(human_scores, judge_scores)

    is_trusted = kappa >= KAPPA_THRESHOLD and accuracy >= ACCURACY_THRESHOLD
    verdict = CalibrationVerdict.TRUSTED if is_trusted else CalibrationVerdict.UNTRUSTED
    now_utc = datetime.now(timezone.utc)

    report: dict[str, Any] = {
        "judge_model": judge_model.id,
        "timestamp": now_utc.isoformat(),
        "n_examples": n_examples,
        "repeats": repeats,
        "accuracy": round(accuracy, 4),
        "cohens_kappa": round(kappa, 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "score_mae": round(score_mae, 4),
        "spearman_rho": round(spearman_rho, 4),
        "self_agreement": round(self_consistent_count / n_examples, 4) if n_examples else 0.0,
        "confusion_matrix": {"tp": tp, "fp": fp, "tn": tn, "fn": fn},
        "verdict": str(verdict),
        "thresholds": {"min_kappa": KAPPA_THRESHOLD, "min_accuracy": ACCURACY_THRESHOLD},
        "disagreements": disagreements,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    safe_model_name = judge_model.id.replace("/", "_")
    timestamp_slug = now_utc.strftime("%Y%m%d_%H%M%S")
    report_path = out_dir / f"{safe_model_name}_{timestamp_slug}.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    report["report_path"] = str(report_path)
    return report


def load_latest_calibration(
    judge_model_id: str = DEFAULT_JUDGE_MODEL_ID,
    out_dir: Path = Path("results/calibration"),
) -> dict[str, Any] | None:
    """Return the most recent persisted calibration JSON report for `judge_model_id`, if any."""
    if not out_dir.exists():
        return None
    safe_model_name = judge_model_id.replace("/", "_")
    matching_reports = sorted(out_dir.glob(f"{safe_model_name}_*.json"))
    if not matching_reports:
        return None
    try:
        parsed_report = json.loads(matching_reports[-1].read_text(encoding="utf-8"))
        return parsed_report if isinstance(parsed_report, dict) else None
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug("Failed to read calibration report %s: %s", matching_reports[-1], exc)
        return None
