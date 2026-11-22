"""Tests for paired bootstrap CI, exact McNemar test, and infra_error exclusion."""

from eval_runner.schemas import TrialResult
from eval_runner.stats import compare_configs, exact_mcnemar_pvalue


def _mk_trial(cfg: str, task: str, idx: int, score: float | None, status: str = "completed") -> TrialResult:
    return TrialResult(
        trial_id=f"{cfg}_{task}_t{idx}",
        experiment_id="exp_test",
        config_name=cfg,
        config_hash="abc123",
        harness="hermes",
        model="mock",
        task_id=task,
        trial_index=idx,
        status=status,  # type: ignore[arg-type]
        score=score,
        passed=(score >= 0.5) if score is not None else None,
        cost_usd=0.01 if status == "completed" else 0.0,
        runtime_sec=2.0,
    )


def test_exact_mcnemar_known_values() -> None:
    # 0 discordant -> p = 1.0
    assert exact_mcnemar_pvalue([True, False], [True, False]) == 1.0
    # 6 wins for B, 0 for A -> 2 * (0.5 ** 6) = 0.03125
    p = exact_mcnemar_pvalue([False] * 6, [True] * 6)
    assert abs(p - 0.03125) < 1e-6


def test_compare_configs_detects_significant_win_and_ignores_infra_errors() -> None:
    tasks = [f"task_{i}" for i in range(6)]
    trials_a = [_mk_trial("A", t, 1, 0.0) for t in tasks]
    trials_b = [_mk_trial("B", t, 1, 1.0) for t in tasks]
    # Add an infra_error trial to B; it must NOT drag down B's score
    trials_b.append(_mk_trial("B", "task_0", 2, None, status="infra_error"))

    report = compare_configs(trials_a, trials_b, "A", "B")
    assert report["delta_mean"] == 1.0
    assert report["verdict"] == "B BETTER"
    assert report["summary_b"]["infra_errors"] == 1
    assert report["summary_b"]["mean_score"] == 1.0


def test_compare_configs_detects_noise() -> None:
    tasks = [f"task_{i}" for i in range(6)]
    trials_a = [_mk_trial("A", t, 1, 1.0 if i % 2 == 0 else 0.0) for i, t in enumerate(tasks)]
    trials_b = [_mk_trial("B", t, 1, 0.0 if i % 2 == 0 else 1.0) for i, t in enumerate(tasks)]
    report = compare_configs(trials_a, trials_b, "A", "B")
    assert report["verdict"] == "NOISE"
