"""CLI entrypoints: eval-run, eval-retry, eval-compare, eval-inspect, eval-export."""

from __future__ import annotations

import json
import os
from pathlib import Path

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from eval_runner.calibration import load_latest_calibration, run_calibration
from eval_runner.failures import compare_failures, summarize_failures
from eval_runner.runner import (
    export_experiment,
    load_experiment_trials,
    retry_experiment,
    run_experiment,
)
from eval_runner.stats import compare_configs, summarize_config

load_dotenv()
console = Console()


def _print_trials_table(exp_id: str, trials: list) -> None:
    table = Table(title=f"Experiment {exp_id}")
    for col in ("Trial ID", "Config", "Task", "Status", "Score", "Time (s)", "Tokens", "Cost ($)"):
        table.add_column(col)
    for t in sorted(trials, key=lambda x: (x.config_name, x.task_id, x.trial_index)):
        status_style = "green" if t.passed else ("yellow" if t.status == "infra_error" else "red")
        score_str = f"{t.score:.2f}" if t.score is not None else "-"
        table.add_row(
            t.trial_id,
            t.config_name,
            t.task_id,
            f"[{status_style}]{t.status}[/{status_style}]",
            score_str,
            f"{t.runtime_sec:.1f}",
            str(t.input_tokens + t.output_tokens),
            f"{t.cost_usd:.5f}",
        )
    console.print(table)


def run_cmd() -> None:
    def _main(
        config: list[Path] = typer.Option(
            [], "--config", "-c", help="One or more config YAML files"
        ),
        harness: list[str] = typer.Option(
            [], "--harness", "-H", help="Harness name(s) for matrix run (e.g. hermes, langgraph)"
        ),
        model: list[str] = typer.Option(
            [],
            "--model",
            "-m",
            help="Model catalog ID or LiteLLM string (e.g. gemini/gemini-2.5-flash)",
        ),
        settings: Path | None = typer.Option(
            None,
            "--settings",
            help="Optional YAML file with shared Settings for --harness/--model runs",
        ),
        tasks: Path = typer.Option(Path("tasks"), "--tasks", "-t", help="Tasks directory or single task"),
        trials: int = typer.Option(1, "--trials", "-n", help="Repeated trials (N) per task"),
        concurrency: int = typer.Option(
            int(os.environ.get("EVAL_CONCURRENCY", "2")), "--concurrency", "-j"
        ),
        seed: int = typer.Option(42, "--seed"),
        exp_id: str | None = typer.Option(None, "--exp-id"),
        image: str | None = typer.Option(None, "--image", help="Override per-harness Docker image"),
    ) -> None:
        eid, results = run_experiment(
            config_paths=config,
            harnesses=harness,
            models=model,
            settings_path=settings,
            tasks_path=tasks,
            n_trials=trials,
            concurrency=concurrency,
            seed=seed,
            experiment_id=exp_id,
            image=image,
        )
        _print_trials_table(eid, results)
        console.print(f"\n[bold]Saved to:[/bold] results/{eid}/")

    typer.run(_main)


def retry_cmd() -> None:
    def _main(
        exp: str = typer.Option(..., "--exp", help="Experiment ID under results/"),
        concurrency: int = typer.Option(
            int(os.environ.get("EVAL_CONCURRENCY", "2")), "--concurrency", "-j"
        ),
        image: str | None = typer.Option(None, "--image", help="Override per-harness Docker image"),
    ) -> None:
        retried = retry_experiment(experiment_id=exp, concurrency=concurrency, image=image)
        if not retried:
            console.print(f"[green]No infra_error or missing trials in {exp}.[/green]")
            return
        _print_trials_table(exp, retried)

    typer.run(_main)


def _print_config_summary_table(by_cfg: dict[str, list]) -> None:
    table = Table(title="Configuration Trade-offs (Quality vs Cost vs Latency)")
    for col in (
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
        table.add_column(col)
    for name in sorted(by_cfg.keys()):
        s = summarize_config(by_cfg[name])
        table.add_row(
            name,
            str(s["completed"]),
            str(s["infra_errors"]),
            f"{s['mean_score']:.3f}",
            f"{s['pass_rate']:.1%}",
            f"{s['avg_cost_usd']:.5f}",
            f"{s['total_cost_usd']:.5f}",
            f"{s['avg_runtime_sec']:.2f}",
            f"{s['p95_runtime_sec']:.2f}",
            str(s["avg_tokens"]),
        )
    console.print(table)


def compare_cmd() -> None:
    def _main(
        exp: str = typer.Option(..., "--exp", help="Experiment ID under results/"),
        a: str | None = typer.Option(None, "--a", help="Config A name (defaults to first)"),
        b: str | None = typer.Option(None, "--b", help="Config B name (defaults to second)"),
    ) -> None:
        exp_dir = Path("results") / exp
        trials = load_experiment_trials(exp_dir)
        if not trials:
            console.print(f"[red]No trials found in results/{exp}/trials.[/red]")
            raise typer.Exit(code=1)

        by_cfg: dict[str, list] = {}
        for t in trials:
            by_cfg.setdefault(t.config_name, []).append(t)

        _print_config_summary_table(by_cfg)
        names = sorted(by_cfg.keys())
        if len(names) < 2:
            console.print("\n[yellow]Only 1 config in experiment; skipping paired comparison.[/yellow]")
            return

        name_a = a or names[0]
        name_b = b or names[1]
        report = compare_configs(by_cfg[name_a], by_cfg[name_b], name_a, name_b)

        console.print(f"\n[bold]Paired Comparison: {name_a} vs {name_b}[/bold]")
        console.print(f"  Delta (B - A): [bold]{report['delta_mean']:+.4f}[/bold]")
        console.print(f"  95% Bootstrap CI: {report['ci_95']}")
        console.print(f"  Exact McNemar p:  {report['mcnemar_p']}")
        console.print(f"  Verdict:          [bold cyan]{report['verdict']}[/bold cyan]")

        for w in report.get("warnings", []):
            console.print(f"  [yellow]WARNING:[/yellow] {w}")

        table = Table(title="Per-Task Deltas")
        for col in ("Task", f"{name_a} (n)", f"{name_b} (n)", "Delta", "95% CI / Noise"):
            table.add_column(col)
        for row in report["per_task"]:
            ci_str = f"{row['ci_95']} {'(noise)' if row.get('is_noise') else ''}".strip()
            table.add_row(
                row["task_id"],
                f"{row['score_a']:.2f} ({row['n_a']})",
                f"{row['score_b']:.2f} ({row['n_b']})",
                f"{row['delta']:+.2f}",
                ci_str,
            )
        console.print(table)

        judge_models = {
            t.grade.details.get("judge_model")
            for t in trials
            if t.grade and t.grade.grader_type == "llm_judge" and isinstance(t.grade.details, dict)
        }
        for jm in sorted(x for x in judge_models if x):
            cal = load_latest_calibration(str(jm))
            if cal:
                console.print(
                    f"\n[bold]Judge calibration ({jm}):[/bold] {cal['verdict']} "
                    f"(kappa={cal['cohens_kappa']}, acc={cal['accuracy']})"
                )
            else:
                console.print(
                    f"\n[yellow]No calibration report found for judge '{jm}'. "
                    f"Run `eval-calibrate --judge {jm}`.[/yellow]"
                )

    typer.run(_main)


def inspect_cmd() -> None:
    def _main(
        trial_file: Path = typer.Option(..., "--trial", help="Path to trial JSON file"),
    ) -> None:
        data = json.loads(trial_file.read_text(encoding="utf-8"))
        trace_path = data.get("trace_path")
        if trace_path and Path(trace_path).exists():
            console.print("[bold]--- Trajectory ---[/bold]")
            type_colors = {
                "session_start": "blue",
                "message": "white",
                "tool_call": "yellow",
                "tool_result": "green",
                "memory_op": "magenta",
                "skill_invoked": "cyan",
                "error": "red",
                "session_end": "blue",
            }
            for line in Path(trace_path).read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                ev = json.loads(line)
                color = type_colors.get(ev["type"], "white")
                console.print(f"[{ev['seq']}] [{color}]{ev['type']}[/{color}]: {ev['payload']}")

        grade = data.get("grade") or {}
        passed = data.get("passed")
        status_str = (
            "[green]PASS[/green]"
            if passed
            else ("[yellow]INFRA_ERROR[/yellow]" if data.get("status") == "infra_error" else "[red]FAIL[/red]")
        )
        verdict_lines = [
            f"Trial: {data.get('trial_id')}  |  Config: {data.get('config_name')} ({data.get('harness')} / {data.get('model')})",
            f"Result: {status_str}  |  Score: {data.get('score')}  |  Failure Category: {data.get('failure_category') or '-'}",
            f"Grader: {grade.get('grader_type', '-')}  |  Reasoning: {grade.get('reasoning') or data.get('error_message') or '-'}",
            f"Usage: {data.get('input_tokens', 0)} in + {data.get('output_tokens', 0)} out tokens  |  Cost: ${data.get('cost_usd', 0.0):.5f}  |  Time: {data.get('runtime_sec', 0.0)}s  |  Steps: {data.get('steps', 0)}",
        ]
        criteria = (grade.get("details") or {}).get("criteria") if isinstance(grade.get("details"), dict) else None
        if criteria:
            verdict_lines.append(f"Judge criteria: {criteria}")
        console.print(Panel("\n".join(verdict_lines), title="Verdict & Metrics"))

    typer.run(_main)


def export_cmd() -> None:
    def _main(
        exp: str = typer.Option(..., "--exp", help="Experiment ID under results/"),
        fmt: str = typer.Option("json", "--format", help="json or csv"),
        out: Path | None = typer.Option(None, "--out", help="Output file path"),
    ) -> None:
        exp_dir = Path("results") / exp
        out_path = out or (exp_dir / f"export.{fmt}")
        export_experiment(exp_dir, fmt, out_path)
        console.print(f"[green]Exported {exp} to {out_path}[/green]")

    typer.run(_main)


def calibrate_cmd() -> None:
    def _main(
        judge: str = typer.Option("gemini-flash", "--judge", help="Judge model ID or LiteLLM string"),
        labels: Path = typer.Option(Path("calibration/judge_labels.jsonl"), "--labels"),
        repeats: int = typer.Option(3, "--repeats", help="Judge repeats per example for self-agreement"),
    ) -> None:
        report = run_calibration(judge_model_id=judge, labels_path=labels, repeats=repeats)
        color = "green" if report["verdict"] == "TRUSTED" else "red"
        console.print(f"\n[bold]Judge Calibration ({report['judge_model']})[/bold]: [{color}]{report['verdict']}[/{color}]")
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
            table = Table(title="Disagreements")
            for col in ("ID", "Task", "Human", "Judge", "Notes / Reasoning"):
                table.add_column(col)
            for d in report["disagreements"]:
                table.add_row(
                    d["id"],
                    d["task_id"],
                    f"{d['human_passed']} ({d['human_score']})",
                    f"{d['judge_passed']} ({d['judge_score']})",
                    f"{d['notes']} | {d['judge_reasoning'][:120]}",
                )
            console.print(table)
        console.print(f"\nSaved to: {report['report_path']}")

    typer.run(_main)


def failures_cmd() -> None:
    def _main(
        exp: str = typer.Option(..., "--exp", help="Experiment ID under results/"),
        a: str | None = typer.Option(None, "--a", help="Optional Config A for delta"),
        b: str | None = typer.Option(None, "--b", help="Optional Config B for delta"),
    ) -> None:
        exp_dir = Path("results") / exp
        trials = load_experiment_trials(exp_dir)
        if not trials:
            console.print(f"[red]No trials found in results/{exp}/trials.[/red]")
            raise typer.Exit(code=1)

        summary = summarize_failures(trials)
        table = Table(title=f"Failure Breakdown — {exp}")
        for col in ("Config", "Failed / Total", "Categories", "Example Trial IDs"):
            table.add_column(col)
        for cfg_name, info in summary.items():
            cats_str = ", ".join(f"{k}: {v}" for k, v in info["categories"].items()) or "(none)"
            ex_str = "; ".join(f"{k}: {v[0]}" for k, v in info["examples"].items() if v) or "-"
            table.add_row(cfg_name, f"{info['failed']} / {info['total']}", cats_str, ex_str)
        console.print(table)

        names = sorted(summary.keys())
        if len(names) >= 2:
            by_cfg: dict[str, list] = {}
            for t in trials:
                by_cfg.setdefault(t.config_name, []).append(t)
            name_a = a or names[0]
            name_b = b or names[1]
            deltas = compare_failures(by_cfg[name_a], by_cfg[name_b], name_a, name_b)
            if deltas:
                dtab = Table(title=f"Failure Category Deltas ({name_b} - {name_a})")
                for col in ("Category", name_a, name_b, "Delta"):
                    dtab.add_column(col)
                for row in deltas:
                    dtab.add_row(row["category"], str(row["count_a"]), str(row["count_b"]), f"{row['delta']:+d}")
                console.print(dtab)

    typer.run(_main)
