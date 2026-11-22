"""Tests for atomic trial persistence and Inspect-style `eval-retry` (only re-runs infra_error)."""

from pathlib import Path
from unittest.mock import patch

from eval_runner.runner import load_experiment_trials, retry_experiment, run_experiment
from eval_runner.schemas import GradeResult, TrialResult


def test_eval_retry_reruns_only_infra_error_trials(tmp_path: Path) -> None:
    calls: list[tuple[str, int]] = []

    def fake_run_single_trial(
        *,
        experiment_id: str,
        task_dir: Path,
        config,
        model,
        catalog,
        trial_index: int,
        results_dir: Path,
        skills_root: Path = Path("skills"),
        image: str | None = None,
    ) -> TrialResult:
        calls.append((task_dir.name, trial_index))
        from eval_runner.schemas import compute_config_hash

        chash = compute_config_hash(config, model)
        tid = f"{config.name}_{chash}_{task_dir.name}_t{trial_index}"
        trials_dir = results_dir / experiment_id / "trials"
        trials_dir.mkdir(parents=True, exist_ok=True)

        # First call to calc-compound-interest fails with infra_error; retry succeeds
        is_first_fail = task_dir.name == "calc-compound-interest" and len(
            [c for c in calls if c[0] == "calc-compound-interest"]
        ) == 1
        if is_first_fail:
            res = TrialResult(
                trial_id=tid,
                experiment_id=experiment_id,
                config_name=config.name,
                config_hash=chash,
                harness=config.harness,
                model=model.id,
                task_id=task_dir.name,
                trial_index=trial_index,
                status="infra_error",
                error_message="429 RateLimitError",
            )
        else:
            res = TrialResult(
                trial_id=tid,
                experiment_id=experiment_id,
                config_name=config.name,
                config_hash=chash,
                harness=config.harness,
                model=model.id,
                task_id=task_dir.name,
                trial_index=trial_index,
                status="completed",
                score=1.0,
                passed=True,
                grade=GradeResult(grader_type="deterministic", score=1.0, passed=True),
            )
        (trials_dir / f"{tid}.json").write_text(res.model_dump_json(indent=2), encoding="utf-8")
        return res

    with patch("eval_runner.runner.run_single_trial", side_effect=fake_run_single_trial), patch(
        "eval_runner.runner.reap_orphan_containers", return_value=0
    ):
        exp_id, first_results = run_experiment(
            harnesses=["langgraph"],
            models=["mock"],
            settings_path=Path("configs/default.yaml"),
            tasks_path=Path("tasks"),
            n_trials=1,
            concurrency=1,
            results_dir=tmp_path,
        )
        assert len(first_results) == 5
        assert sum(1 for r in first_results if r.status == "infra_error") == 1

        # Now run eval-retry: MUST re-run ONLY the 1 infra_error trial
        retried = retry_experiment(experiment_id=exp_id, concurrency=1, results_dir=tmp_path)
        assert len(retried) == 1
        assert retried[0].task_id == "calc-compound-interest"
        assert retried[0].status == "completed"

        all_trials = load_experiment_trials(tmp_path / exp_id)
        assert len(all_trials) == 5
        assert all(t.status == "completed" for t in all_trials)
