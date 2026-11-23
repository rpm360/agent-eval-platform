# Experiment Guide

[← Back to Docs](./README.md) · **[Read the Full Experiment Report →](./EXPERIMENT_RESULTS.md)**

## What We Test (The 24-Task Suite)

The benchmark ships with **24 tasks** in [`tasks/`](../tasks/) across five real-world buckets, including tasks built specifically to separate **Memory ON vs. OFF** and **Skills ON vs. OFF**:

| Bucket | Count | Example Tasks | How It's Graded |
| :--- | :---: | :--- | :--- |
| **Coding & Bug Fixes** | 5 | `code-fix-lru-cache`, `code-fix-binary-search`, `code-fix-multi-file` | Hidden `pytest` unit tests |
| **Math, Data & Files** | 8 | `calc-compound-interest`, `file-csv-aggregate`, `data-log-error-counts` | Exact value, JSON & file checks |
| **Memory Recall** | 3 | `mem-deploy-convention`, `mem-api-version-header`, `mem-db-table-naming` | Checks rules recalled from `MEMORY.md` |
| **Procedural Skills** | 3 | `skill-release-tag`, `skill-changelog-entry`, `skill-commit-message` | Checks formats loaded from `SKILL.md` |
| **Writing & Review** | 5 | `judge-code-review`, `judge-api-docs`, `judge-incident-postmortem` | AI judge with a strict rubric |

### Grader Design & Validation ([`eval_runner/graders.py`](../eval_runner/graders.py))

- **Hidden test scripts (19 tasks):** The `tests/` folder is copied into the container *only after* the agent finishes, so the agent can never peek at or edit the answer key. Validated automatically via [`tests/test_tasks_lint.py`](../tests/test_tasks_lint.py) and mock smoke runs.
- **Calibrated AI judge (5 tasks):** Open-ended writing and code reviews are graded against a rubric at `temperature = 0`. Before trusting the judge, we tested it on **30 human-labelled examples** ([`calibration/judge_labels.jsonl`](../calibration/judge_labels.jsonl) via [`eval_runner/calibration.py`](../eval_runner/calibration.py)). It matched human pass/fail calls **93.3% of the time** ([Cohen's kappa](https://en.wikipedia.org/wiki/Cohen%27s_kappa) = 0.87, well above our 0.60 bar).

---

## Statistical Method & How We Chose N ([`eval_runner/stats.py`](../eval_runner/stats.py))

Agents are non-deterministic, so comparing Config A against Config B on a single run can be misleading. Here is how we keep comparisons honest without heavy math:

- **Compare task-by-task:** We compare A and B on the *same* tasks (ignoring any `infra_error` runs) so easy and hard tasks don't skew the gap.
- **Confidence range & noise filter:** We use a [paired bootstrap confidence interval](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.bootstrap.html) (10,000 resamples) alongside [McNemar's test](https://en.wikipedia.org/wiki/McNemar%27s_test) for pass/fail flips. If zero sits inside the 95% confidence range, the dashboard calls the difference **`NOISE`** instead of declaring a false winner.
- **How we pick `N` (repeats per task):**
  - **`N = 1`** for quick smoke tests or full-suite sweeps across all 19–24 tasks.
  - **`N = 2 to 3`** for standard comparisons at low temperature (`0.2`), which smooths out most single-run flukes.
  - **`N = 3 to 5`** for higher-temperature or AI-judged tasks. Beyond 5 repeats, adding *more tasks* improves confidence much faster than running the same task over and over.

---

## Honest Limits

- **Small runs have wide error bars.** With `N = 1` or fewer than 10 tasks, only large gaps will clear the noise filter. The dashboard displays an automatic warning whenever a run has `N < 3` or saturated tasks.
- **Tied pass rates test efficiency, not intelligence.** When two configs solve the exact same tasks (see our **[Hermes vs. LangGraph report](./EXPERIMENT_RESULTS.md)**), use the results to compare token cost, runtime, and failure modes.
- **AI judges can be generous on borderline answers.** Use a judge from a different model family when comparing two model providers head-to-head.
