"""CLI entrypoints: eval-run, eval-retry, eval-compare, eval-inspect, eval-export."""

from __future__ import annotations

import json
import os
from pathlib import Path

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

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


def compare_cmd() -> None:
    def _main(
        exp: str = typer.Option(..., "--exp", help="Experiment ID under results/"),
        a: str | None = typer.Option(None, "--a", help="Config A name (defaults to first)"),
        b: str | None = typer.Option(None, "--b", help="Config B name (defaults to second)"),
    ) -> None:
        exp_dir = Path("results") / exp
        trials = load_experiment_trials(exp_dir)
        by_cfg: dict[str, list] = {}
        for t in trials:
            by_cfg.setdefault(t.config_name, []).append(t)

        names = sorted(by_cfg.keys())
        if len(names) == 1:
            console.print(f"[bold]{names[0]}[/bold]:", summarize_config(by_cfg[names[0]]))
            return
        name_a = a or names[0]
        name_b = b or names[1]
        report = compare_configs(by_cfg[name_a], by_cfg[name_b], name_a, name_b)

        console.print(f"\n[bold]Comparison: {name_a} vs {name_b}[/bold]")
        console.print(f"  Delta (B - A): [bold]{report['delta_mean']:+.4f}[/bold]")
        console.print(f"  95% Bootstrap CI: {report['ci_95']}")
        console.print(f"  Exact McNemar p:  {report['mcnemar_p']}")
        console.print(f"  Verdict:          [bold cyan]{report['verdict']}[/bold cyan]")

        table = Table(title="Per-Task Deltas")
        for col in ("Task", f"{name_a} (n)", f"{name_b} (n)", "Delta"):
            table.add_column(col)
        for row in report["per_task"]:
            table.add_row(
                row["task_id"],
                f"{row['score_a']:.2f} ({row['n_a']})",
                f"{row['score_b']:.2f} ({row['n_b']})",
                f"{row['delta']:+.2f}",
            )
        console.print(table)
        console.print(f"\nConfig A summary: {report['summary_a']}")
        console.print(f"Config B summary: {report['summary_b']}")

    typer.run(_main)


def inspect_cmd() -> None:
    def _main(
        trial_file: Path = typer.Option(..., "--trial", help="Path to trial JSON file"),
    ) -> None:
        data = json.loads(trial_file.read_text(encoding="utf-8"))
        console.print_json(data=data)
        trace_path = data.get("trace_path")
        if trace_path and Path(trace_path).exists():
            console.print("\n[bold]--- Trajectory ---[/bold]")
            for line in Path(trace_path).read_text(encoding="utf-8").splitlines():
                ev = json.loads(line)
                console.print(f"[{ev['seq']}] [cyan]{ev['type']}[/cyan]: {ev['payload']}")

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
