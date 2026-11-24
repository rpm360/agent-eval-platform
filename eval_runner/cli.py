"""CLI entrypoints: `eval-run`, `eval-retry`, `eval-compare`, `eval-inspect`, `eval-export`, `eval-calibrate`, `eval-failures`."""

from __future__ import annotations

import json
import os
from pathlib import Path

import typer
from dotenv import load_dotenv
from rich.console import Console

from eval_runner.calibration import run_calibration
from eval_runner.cli_formatters import (
    group_trials_by_config,
    print_calibration_report,
    print_config_summary_table,
    print_failure_breakdown,
    print_paired_comparison_report,
    print_trial_inspection,
    print_trials_table,
)
from eval_runner.constants import (
    DEFAULT_CALIBRATION_REPEATS,
    DEFAULT_CONCURRENCY,
    DEFAULT_JUDGE_MODEL_ID,
    DEFAULT_RANDOM_SEED,
)
from eval_runner.runner import (
    export_experiment,
    load_experiment_trials,
    retry_experiment,
    run_experiment,
)
from eval_runner.stats import compare_configs

load_dotenv(override=True)
console = Console()


def _default_concurrency() -> int:
    return int(os.environ.get("EVAL_CONCURRENCY", str(DEFAULT_CONCURRENCY)))


def run_cmd() -> None:
    """Execute a declarative config or harness x model evaluation matrix."""

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
        tasks: list[Path] = typer.Option(
            [], "--tasks", "-t", help="One or more task directories (defaults to tasks/)"
        ),
        trials: int = typer.Option(1, "--trials", "-n", help="Repeated trials (N) per task"),
        concurrency: int = typer.Option(_default_concurrency(), "--concurrency", "-j"),
        seed: int = typer.Option(DEFAULT_RANDOM_SEED, "--seed"),
        exp_id: str | None = typer.Option(None, "--exp-id"),
        image: str | None = typer.Option(None, "--image", help="Override per-harness Docker image"),
    ) -> None:
        experiment_id, trial_results = run_experiment(
            config_paths=config,
            harnesses=harness,
            models=model,
            settings_path=settings,
            tasks_path=tasks if tasks else Path("tasks"),
            n_trials=trials,
            concurrency=concurrency,
            seed=seed,
            experiment_id=exp_id,
            image=image,
        )
        print_trials_table(console, experiment_id, trial_results)
        console.print(f"\n[bold]Saved to:[/bold] results/{experiment_id}/")

    typer.run(_main)


def retry_cmd() -> None:
    """Re-run only `infra_error` or missing trials for an existing experiment."""

    def _main(
        exp: str = typer.Option(..., "--exp", help="Experiment ID under results/"),
        concurrency: int = typer.Option(_default_concurrency(), "--concurrency", "-j"),
        image: str | None = typer.Option(None, "--image", help="Override per-harness Docker image"),
    ) -> None:
        retried_trials = retry_experiment(experiment_id=exp, concurrency=concurrency, image=image)
        if not retried_trials:
            console.print(f"[green]No infra_error or missing trials in {exp}.[/green]")
            return
        print_trials_table(console, exp, retried_trials)

    typer.run(_main)


def compare_cmd() -> None:
    """Compare two configuration arms within an experiment using paired bootstrap + McNemar."""

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

        trials_by_config = group_trials_by_config(trials)
        print_config_summary_table(console, trials_by_config)

        config_names = sorted(trials_by_config.keys())
        if len(config_names) < 2:
            console.print(
                "\n[yellow]Only 1 config in experiment; skipping paired comparison.[/yellow]"
            )
            return

        name_a = a or config_names[0]
        name_b = b or config_names[1]
        comparison_report = compare_configs(
            trials_by_config[name_a], trials_by_config[name_b], name_a, name_b
        )
        print_paired_comparison_report(console, comparison_report, trials)

    typer.run(_main)


def inspect_cmd() -> None:
    """Display the trajectory event log and grading summary for one trial JSON file."""

    def _main(
        trial_file: Path = typer.Option(..., "--trial", help="Path to trial JSON file"),
    ) -> None:
        trial_data = json.loads(trial_file.read_text(encoding="utf-8"))
        print_trial_inspection(console, trial_data)

    typer.run(_main)


def export_cmd() -> None:
    """Export an experiment's trials to JSON or CSV."""

    def _main(
        exp: str = typer.Option(..., "--exp", help="Experiment ID under results/"),
        fmt: str = typer.Option("json", "--format", help="json or csv"),
        out: Path | None = typer.Option(None, "--out", help="Output file path"),
    ) -> None:
        exp_dir = Path("results") / exp
        output_path = out or (exp_dir / f"export.{fmt}")
        export_experiment(exp_dir, fmt, output_path)
        console.print(f"[green]Exported {exp} to {output_path}[/green]")

    typer.run(_main)


def calibrate_cmd() -> None:
    """Evaluate LLM-as-judge agreement against human-labelled examples."""

    def _main(
        judge: str = typer.Option(
            DEFAULT_JUDGE_MODEL_ID, "--judge", help="Judge model ID or LiteLLM string"
        ),
        labels: Path = typer.Option(Path("calibration/judge_labels.jsonl"), "--labels"),
        repeats: int = typer.Option(
            DEFAULT_CALIBRATION_REPEATS,
            "--repeats",
            help="Judge repeats per example for self-agreement",
        ),
    ) -> None:
        report = run_calibration(judge_model_id=judge, labels_path=labels, repeats=repeats)
        print_calibration_report(console, report)

    typer.run(_main)


def failures_cmd() -> None:
    """Summarize failure taxonomy counts and category deltas across configs."""

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
        print_failure_breakdown(console, exp, trials, config_a=a, config_b=b)

    typer.run(_main)
