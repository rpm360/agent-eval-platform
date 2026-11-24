"""Rich console tables and panels for CLI reporting commands."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from eval_runner.calibration import load_latest_calibration
from eval_runner.constants import CalibrationVerdict, GraderType, TrialStatus
from eval_runner.failures import compare_failures, summarize_failures
from eval_runner.schemas import TrialResult
from eval_runner.stats import summarize_config

DISAGREEMENT_REASONING_PREVIEW_CHARS = 120

TRACE_EVENT_COLORS: dict[str, str] = {
    "session_start": "blue",
    "message": "white",
    "tool_call": "yellow",
    "tool_result": "green",
    "memory_op": "magenta",
    "skill_invoked": "cyan",
    "error": "red",
    "session_end": "blue",
}


def group_trials_by_config(trials: list[TrialResult]) -> dict[str, list[TrialResult]]:
    """Group `TrialResult` records by `config_name`."""
    grouped: dict[str, list[TrialResult]] = defaultdict(list)
    for trial in trials:
        grouped[trial.config_name].append(trial)
    return dict(grouped)


def print_trials_table(console: Console, exp_id: str, trials: list[TrialResult]) -> None:
    """Render per-trial status, score, runtime, token usage, and USD cost."""
    table = Table(title=f"Experiment {exp_id}")
    for column in (
        "Trial ID",
        "Config",
        "Task",
        "Status",
        "Score",
        "Time (s)",
        "Tokens",
        "Cost ($)",
    ):
        table.add_column(column)

    sorted_trials = sorted(
        trials, key=lambda trial: (trial.config_name, trial.task_id, trial.trial_index)
    )
    for trial in sorted_trials:
        status_style = (
            "green"
            if trial.passed
            else ("yellow" if trial.status == TrialStatus.INFRA_ERROR else "red")
        )
        score_display = f"{trial.score:.2f}" if trial.score is not None else "-"
        table.add_row(
            trial.trial_id,
            trial.config_name,
            trial.task_id,
            f"[{status_style}]{trial.status}[/{status_style}]",
            score_display,
            f"{trial.runtime_sec:.1f}",
            str(trial.input_tokens + trial.output_tokens),
            f"{trial.cost_usd:.5f}",
        )
    console.print(table)


def print_config_summary_table(
    console: Console, trials_by_config: dict[str, list[TrialResult]]
) -> None:
    """Render aggregated quality, cost, and latency metrics per configuration arm."""
    table = Table(title="Configuration Trade-offs (Quality vs Cost vs Latency)")
    for column in (
        "Config",
        "Done",
        "InfraErr",
        "Mean Score",
        "Pass Rate",
        "Avg Cost ($)",
        "Total Cost ($)",
        "Avg Time (s)",
        "p95 Time (s)",
        "Avg Tokens",
    ):
        table.add_column(column)

    for config_name in sorted(trials_by_config.keys()):
        metric_summary = summarize_config(trials_by_config[config_name])
        table.add_row(
            config_name,
            str(metric_summary["completed"]),
            str(metric_summary["infra_errors"]),
            f"{metric_summary['mean_score']:.3f}",
            f"{metric_summary['pass_rate']:.1%}",
            f"{metric_summary['avg_cost_usd']:.5f}",
            f"{metric_summary['total_cost_usd']:.5f}",
            f"{metric_summary['avg_runtime_sec']:.2f}",
            f"{metric_summary['p95_runtime_sec']:.2f}",
            str(metric_summary["avg_tokens"]),
        )
    console.print(table)


def print_paired_comparison_report(
    console: Console,
    report: dict[str, Any],
    trials: list[TrialResult],
) -> None:
    """Render headline statistical comparison, warnings, per-task deltas, and judge trust status."""
    name_a = report["config_a"]
    name_b = report["config_b"]

    console.print(f"\n[bold]Paired Comparison: {name_a} vs {name_b}[/bold]")
    console.print(f"  Delta (B - A): [bold]{report['delta_mean']:+.4f}[/bold]")
    console.print(f"  95% Bootstrap CI: {report['ci_95']}")
    console.print(f"  Exact McNemar p:  {report['mcnemar_p']}")
    console.print(f"  Verdict:          [bold cyan]{report['verdict']}[/bold cyan]")

    for warning_text in report.get("warnings", []):
        console.print(f"  [yellow]WARNING:[/yellow] {warning_text}")

    task_table = Table(title="Per-Task Deltas")
    for column in ("Task", f"{name_a} (n)", f"{name_b} (n)", "Delta", "95% CI / Noise"):
        task_table.add_column(column)
    for task_row in report["per_task"]:
        ci_label = f"{task_row['ci_95']} {'(noise)' if task_row.get('is_noise') else ''}".strip()
        task_table.add_row(
            task_row["task_id"],
            f"{task_row['score_a']:.2f} ({task_row['n_a']})",
            f"{task_row['score_b']:.2f} ({task_row['n_b']})",
            f"{task_row['delta']:+.2f}",
            ci_label,
        )
    console.print(task_table)

    judge_models = {
        trial.grade.details.get("judge_model")
        for trial in trials
        if trial.grade
        and trial.grade.grader_type == GraderType.LLM_JUDGE
        and isinstance(trial.grade.details, dict)
    }
    for judge_model in sorted(str(model_id) for model_id in judge_models if model_id):
        calibration_report = load_latest_calibration(judge_model)
        if calibration_report:
            console.print(
                f"\n[bold]Judge calibration ({judge_model}):[/bold] {calibration_report['verdict']} "
                f"(kappa={calibration_report['cohens_kappa']}, acc={calibration_report['accuracy']})"
            )
        else:
            console.print(
                f"\n[yellow]No calibration report found for judge '{judge_model}'. "
                f"Run `eval-calibrate --judge {judge_model}`.[/yellow]"
            )


def print_trial_inspection(console: Console, trial_data: dict[str, Any]) -> None:
    """Render step-by-step trajectory events and verdict summary panel for a single trial."""
    trace_path_str = trial_data.get("trace_path")
    if trace_path_str and Path(trace_path_str).exists():
        console.print("[bold]--- Trajectory ---[/bold]")
        for raw_line in Path(trace_path_str).read_text(encoding="utf-8").splitlines():
            if not raw_line.strip():
                continue
            trace_event = json.loads(raw_line)
            color = TRACE_EVENT_COLORS.get(trace_event["type"], "white")
            console.print(
                f"[{trace_event['seq']}] [{color}]{trace_event['type']}[/{color}]: "
                f"{trace_event['payload']}"
            )

    grade = trial_data.get("grade") or {}
    passed = trial_data.get("passed")
    if passed:
        status_badge = "[green]PASS[/green]"
    elif trial_data.get("status") == TrialStatus.INFRA_ERROR:
        status_badge = "[yellow]INFRA_ERROR[/yellow]"
    else:
        status_badge = "[red]FAIL[/red]"

    verdict_lines = [
        f"Trial: {trial_data.get('trial_id')}  |  Config: {trial_data.get('config_name')} "
        f"({trial_data.get('harness')} / {trial_data.get('model')})",
        f"Result: {status_badge}  |  Score: {trial_data.get('score')}  |  "
        f"Failure Category: {trial_data.get('failure_category') or '-'}",
        f"Grader: {grade.get('grader_type', '-')}  |  "
        f"Reasoning: {grade.get('reasoning') or trial_data.get('error_message') or '-'}",
        f"Usage: {trial_data.get('input_tokens', 0)} in + {trial_data.get('output_tokens', 0)} out tokens  |  "
        f"Cost: ${trial_data.get('cost_usd', 0.0):.5f}  |  "
        f"Time: {trial_data.get('runtime_sec', 0.0)}s  |  Steps: {trial_data.get('steps', 0)}",
    ]
    details = grade.get("details")
    criteria = details.get("criteria") if isinstance(details, dict) else None
    if criteria:
        verdict_lines.append(f"Judge criteria: {criteria}")
    console.print(Panel("\n".join(verdict_lines), title="Verdict & Metrics"))


def print_calibration_report(console: Console, report: dict[str, Any]) -> None:
    """Render LLM-as-judge calibration metrics and human-vs-judge disagreements."""
    verdict_color = "green" if report["verdict"] == CalibrationVerdict.TRUSTED else "red"
    console.print(
        f"\n[bold]Judge Calibration ({report['judge_model']})[/bold]: "
        f"[{verdict_color}]{report['verdict']}[/{verdict_color}]"
    )
    console.print(
        f"  Examples: {report['n_examples']} (x{report['repeats']} repeats)  |  "
        f"Accuracy: {report['accuracy']:.3f}  |  Cohen's kappa: {report['cohens_kappa']:.3f}"
    )
    console.print(
        f"  Precision: {report['precision']:.3f}  |  Recall: {report['recall']:.3f}  |  "
        f"Score MAE: {report['score_mae']:.3f}  |  Spearman rho: {report['spearman_rho']:.3f}  |  "
        f"Self-agreement: {report['self_agreement']:.3f}"
    )
    console.print(f"  Confusion: {report['confusion_matrix']}")

    if report["disagreements"]:
        disagreements_table = Table(title="Disagreements")
        for column in ("ID", "Task", "Human", "Judge", "Notes / Reasoning"):
            disagreements_table.add_column(column)
        for item in report["disagreements"]:
            reasoning_snippet = item["judge_reasoning"][:DISAGREEMENT_REASONING_PREVIEW_CHARS]
            disagreements_table.add_row(
                item["id"],
                item["task_id"],
                f"{item['human_passed']} ({item['human_score']})",
                f"{item['judge_passed']} ({item['judge_score']})",
                f"{item['notes']} | {reasoning_snippet}",
            )
        console.print(disagreements_table)
    console.print(f"\nSaved to: {report['report_path']}")


def print_failure_breakdown(
    console: Console,
    exp_id: str,
    trials: list[TrialResult],
    config_a: str | None,
    config_b: str | None,
) -> None:
    """Render failure taxonomy summary per config and optional pairwise category deltas."""
    failure_summary = summarize_failures(trials)
    summary_table = Table(title=f"Failure Breakdown — {exp_id}")
    for column in ("Config", "Failed / Total", "Categories", "Example Trial IDs"):
        summary_table.add_column(column)

    for config_name, config_failures in failure_summary.items():
        categories_str = (
            ", ".join(f"{cat}: {cnt}" for cat, cnt in config_failures["categories"].items())
            or "(none)"
        )
        examples_str = (
            "; ".join(
                f"{cat}: {example_ids[0]}"
                for cat, example_ids in config_failures["examples"].items()
                if example_ids
            )
            or "-"
        )
        summary_table.add_row(
            config_name,
            f"{config_failures['failed']} / {config_failures['total']}",
            categories_str,
            examples_str,
        )
    console.print(summary_table)

    config_names = sorted(failure_summary.keys())
    if len(config_names) < 2:
        return

    trials_by_config = group_trials_by_config(trials)
    name_a = config_a or config_names[0]
    name_b = config_b or config_names[1]
    category_deltas = compare_failures(
        trials_by_config[name_a], trials_by_config[name_b], name_a, name_b
    )
    if not category_deltas:
        return

    delta_table = Table(title=f"Failure Category Deltas ({name_b} - {name_a})")
    for column in ("Category", name_a, name_b, "Delta"):
        delta_table.add_column(column)
    for delta_row in category_deltas:
        delta_table.add_row(
            delta_row["category"],
            str(delta_row["count_a"]),
            str(delta_row["count_b"]),
            f"{delta_row['delta']:+d}",
        )
    console.print(delta_table)
