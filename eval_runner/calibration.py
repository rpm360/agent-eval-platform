"""LLM-as-judge calibration against human-labelled examples (Cohen's kappa, accuracy, consistency)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import BaseModel, Field
from scipy.stats import spearmanr

from eval_runner.graders import grade_llm_judge
from eval_runner.models import load_models_catalog, resolve_model
from eval_runner.schemas import ModelCatalog, TaskSpec

KAPPA_THRESHOLD = 0.6
ACCURACY_THRESHOLD = 0.8


class CalibrationExample(BaseModel):
    id: str
    task_id: str
    artifacts: dict[str, str] = Field(default_factory=dict)
    final_answer: str = ""
    human_passed: bool
    human_score: float = Field(ge=0.0, le=1.0)
    labeler: str = "human"
    notes: str = ""


def load_calibration_labels(path: Path = Path("calibration/judge_labels.jsonl")) -> list[CalibrationExample]:
    examples: list[CalibrationExample] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        examples.append(CalibrationExample.model_validate_json(line))
    return examples


def cohens_kappa(y_true: list[bool], y_pred: list[bool]) -> float:
    """Compute Cohen's kappa for binary pass/fail labels."""
    if len(y_true) != len(y_pred) or not y_true:
        return 0.0
    n = len(y_true)
    tp = sum(1 for yt, yp in zip(y_true, y_pred) if yt and yp)
    tn = sum(1 for yt, yp in zip(y_true, y_pred) if (not yt) and (not yp))
    fp = sum(1 for yt, yp in zip(y_true, y_pred) if (not yt) and yp)
    fn = sum(1 for yt, yp in zip(y_true, y_pred) if yt and (not yp))

    po = (tp + tn) / n
    pe = (((tp + fp) * (tp + fn)) + ((fn + tn) * (fp + tn))) / (n * n)
    if pe >= 1.0:
        return 1.0 if po == 1.0 else 0.0
    return (po - pe) / (1.0 - pe)


def run_calibration(
    *,
    judge_model_id: str = "gemini-flash",
    labels_path: Path = Path("calibration/judge_labels.jsonl"),
    tasks_root: Path = Path("tasks"),
    repeats: int = 3,
    models_path: Path = Path("models.yaml"),
    out_dir: Path = Path("results/calibration"),
) -> dict[str, Any]:
    """Run the LLM judge over human-labelled examples and compute agreement & trust verdict."""
    catalog = load_models_catalog(models_path) if models_path.exists() else ModelCatalog(models=[])
    judge_model = resolve_model(catalog, judge_model_id)
    examples = load_calibration_labels(labels_path)

    task_cache: dict[str, tuple[TaskSpec, str]] = {}
    for ex in examples:
        if ex.task_id not in task_cache:
            tdir = tasks_root / ex.task_id
            task = TaskSpec.from_dir(tdir)
            task = task.model_copy(
                update={"grader": task.grader.model_copy(update={"judge_model": judge_model.id})}
            )
            instr = (tdir / "instruction.md").read_text(encoding="utf-8").strip()
            task_cache[ex.task_id] = (task, instr)

    y_true: list[bool] = []
    y_pred: list[bool] = []
    human_scores: list[float] = []
    judge_scores: list[float] = []
    self_consistent_count = 0
    disagreements: list[dict[str, Any]] = []

    for ex in examples:
        task, instr = task_cache[ex.task_id]
        run_passes: list[bool] = []
        run_scores: list[float] = []
        last_reason = ""
        for _ in range(max(1, repeats)):
            res = grade_llm_judge(
                task=task,
                instruction=instr,
                final_answer=ex.final_answer,
                catalog=catalog,
                artifacts_content=ex.artifacts,
            )
            run_passes.append(bool(res.passed))
            run_scores.append(float(res.score))
            last_reason = res.reasoning

        if len(set(run_passes)) == 1:
            self_consistent_count += 1

        maj_pass = sum(1 for p in run_passes if p) > (len(run_passes) / 2.0)
        mean_score = float(np.mean(run_scores))

        y_true.append(ex.human_passed)
        y_pred.append(maj_pass)
        human_scores.append(ex.human_score)
        judge_scores.append(mean_score)

        if maj_pass != ex.human_passed:
            disagreements.append(
                {
                    "id": ex.id,
                    "task_id": ex.task_id,
                    "human_passed": ex.human_passed,
                    "human_score": ex.human_score,
                    "judge_passed": maj_pass,
                    "judge_score": round(mean_score, 3),
                    "notes": ex.notes,
                    "judge_reasoning": last_reason,
                }
            )

    n = len(examples)
    tp = sum(1 for yt, yp in zip(y_true, y_pred) if yt and yp)
    tn = sum(1 for yt, yp in zip(y_true, y_pred) if (not yt) and (not yp))
    fp = sum(1 for yt, yp in zip(y_true, y_pred) if (not yt) and yp)
    fn = sum(1 for yt, yp in zip(y_true, y_pred) if yt and (not yp))

    accuracy = (tp + tn) / n if n else 0.0
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    kappa = cohens_kappa(y_true, y_pred)
    mae = float(np.mean(np.abs(np.array(judge_scores) - np.array(human_scores)))) if n else 0.0
    if n >= 2 and len(set(human_scores)) > 1 and len(set(judge_scores)) > 1:
        rho_val = spearmanr(human_scores, judge_scores).statistic
        if np.isnan(rho_val):
            rho_val = 0.0
    else:
        rho_val = 0.0

    trusted = kappa >= KAPPA_THRESHOLD and accuracy >= ACCURACY_THRESHOLD
    report = {
        "judge_model": judge_model.id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "n_examples": n,
        "repeats": repeats,
        "accuracy": round(accuracy, 4),
        "cohens_kappa": round(kappa, 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "score_mae": round(mae, 4),
        "spearman_rho": round(float(rho_val), 4),
        "self_agreement": round(self_consistent_count / n, 4) if n else 0.0,
        "confusion_matrix": {"tp": tp, "fp": fp, "tn": tn, "fn": fn},
        "verdict": "TRUSTED" if trusted else "UNTRUSTED",
        "thresholds": {"min_kappa": KAPPA_THRESHOLD, "min_accuracy": ACCURACY_THRESHOLD},
        "disagreements": disagreements,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    safe_name = judge_model.id.replace("/", "_")
    ts_slug = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"{safe_name}_{ts_slug}.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    report["report_path"] = str(out_path)
    return report


def load_latest_calibration(
    judge_model_id: str = "gemini-flash",
    out_dir: Path = Path("results/calibration"),
) -> dict[str, Any] | None:
    if not out_dir.exists():
        return None
    safe_name = judge_model_id.replace("/", "_")
    matches = sorted(out_dir.glob(f"{safe_name}_*.json"))
    if not matches:
        return None
    try:
        return json.loads(matches[-1].read_text(encoding="utf-8"))
    except Exception:
        return None
