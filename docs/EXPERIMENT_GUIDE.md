# Experiment Guide

[← Back to Docs](./README.md)

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
  - **`N = 1`** for quick smoke tests when checking that a new model or harness works.
  - **`N = 2 to 3`** for standard comparisons at low temperature (`0.2`), which smooths out most single-run flukes.
  - **`N = 3 to 5`** for higher-temperature or AI-judged tasks. Beyond 5 repeats, adding *more tasks* improves confidence much faster than running the same task over and over.

---

## The Core Story: Hermes vs. LangGraph

**The question:** If we give the exact same Gemini model to two different agent harnesses, does the harness change the result?

| Metric (5 tasks × 2 repeats) | Hermes | LangGraph |
| :--- | :---: | :---: |
| **Pass rate** | 100% | 100% |
| **Avg time per attempt** | ~18.7s | ~15.1s |
| **Avg tokens per attempt** | ~18,500 | ~3,300 |
| **Quality verdict** | **No real difference (`NOISE`)** | |

- **Quality was a tie, cost was not.** Both solved every task, so the platform rightly called quality a tie. However, LangGraph finished ~20% faster and used **5–6× fewer tokens** on short tasks because Hermes loads a much larger built-in prompt and toolset on every turn.
- **Traces caught a hidden conflict.** In an early run, Hermes failed a memory task while passing everything else. Inspecting the trace ([`eval-inspect`](../eval_runner/cli.py)) showed why: a *skill* and a *memory note* both talked about "release tags," and Hermes trusted the skill over its memory. Disambiguating the task fixed it immediately.

---

## Honest Limits

- **Small runs have wide error bars.** With fewer than 10 tasks or fewer than 3 repeats per task, only large gaps will clear the noise filter. The dashboard displays an automatic warning when a run is under-powered.
- **100% vs. 100% only tests efficiency.** When tasks are too easy for both configs, use the results to compare cost and speed, not intelligence.
- **AI judges can be generous on borderline answers.** Use a judge from a different model family when comparing two model providers head-to-head.
