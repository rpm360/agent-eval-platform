# Experiment Guide

[← Back to Docs](./README.md)

## What We Test (The 24-Task Suite)

The benchmark ships with **24 tasks** grouped into five real-world buckets, including tasks specifically designed to tell **Memory ON vs. OFF** and **Skills ON vs. OFF** apart:

| Bucket | Count | Tasks Included | How It's Graded |
| :--- | :---: | :--- | :--- |
| **Coding & Bug Fixes** | 5 | `code-fix-lru-cache`, `code-fix-binary-search`, `code-fix-multi-file`, `code-implement-roman`, `code-add-type-validation` | Hidden `pytest` unit tests |
| **Math, Data & Files** | 8 | `calc-compound-interest`, `calc-loan-amortization`, `file-csv-aggregate`, `data-csv-join`, `data-json-transform`, `data-log-error-counts`, `fs-find-largest-file`, `fs-normalize-filenames` | Exact value, JSON & file-state checks |
| **Memory Recall** | 3 | `mem-deploy-convention`, `mem-api-version-header`, `mem-db-table-naming` | Deterministic check on rules from `MEMORY.md` |
| **Procedural Skills** | 3 | `skill-release-tag`, `skill-changelog-entry`, `skill-commit-message` | Deterministic check on formats from `SKILL.md` |
| **Writing & Reasoning** | 5 | `judge-code-review`, `judge-api-docs`, `judge-explain-bug`, `judge-incident-postmortem`, `judge-support-reply` | LLM-as-judge with a rubric |

### How Grading Stays Fair

- **Deterministic graders (19 tasks):** Verification scripts and `pytest` suites are injected into the container *only after* the agent exits, so an agent can never read or tamper with the tests.
- **Calibrated AI judge (5 tasks):** Open-ended tasks are graded against a strict rubric at `temperature = 0`. Before trusting the judge, we tested it against **30 human-labelled examples**—it matched human pass/fail calls **93% of the time** (Cohen's κ ≈ 0.87, well above our 0.60 trust bar).

---

## The Core Story: Hermes vs. LangGraph

**The question:** We gave the same model (Gemini) to two different agent harnesses. Does the harness change the outcome?

**What we expected:** Both should solve simple coding, math, and file tasks. Hermes ships with a much richer built-in toolkit and system prompt, so we expected it to cost more per attempt.

**Setup:** 5 tasks × 2 attempts each, per harness. Same model, same settings, memory and skills enabled.

### What Actually Happened

| | Hermes | LangGraph |
| :--- | :---: | :---: |
| Pass rate | 100% | 100% |
| Avg time per attempt | ~18.7s | ~15.1s |
| Avg tokens per attempt | ~18,500 | ~3,300 |
| Verdict on quality | **No real difference (noise)** | |

- **Quality was a tie.** Both solved every task, so the platform correctly reported *noise* instead of crowning a winner.
- **Cost was not a tie.** LangGraph was about 20% faster and used about **5–6× fewer tokens** on these simple tasks.
- **The gap shrinks on longer tasks.** On multi-step tasks LangGraph takes more turns, so its token count rises toward Hermes's.

### The Most Useful Finding Came From a Failure

Early on, Hermes kept failing a memory task while passing everything else. Replaying the trace showed why. A **skill** and a **memory note** both described "release tags," and Hermes trusted the skill over its memory.

Without step-by-step traces, that failure would have looked like "Hermes is bad at memory." In fact the task itself was ambiguous. We fixed the task, and Hermes passed all three memory tasks.

**Why it matters:** the platform tells you *why* a score changed, not just *that* it changed.

---

## Honest Limits

- **Small samples mean wide error bars.** With fewer than ~10 tasks or fewer than 3 attempts per task, even a big gap may be labelled *noise*. The dashboard warns you when this applies.
- **Easy tasks can't separate strong agents.** If both sides score 100%, you learn about cost and speed, not about which agent is smarter.
- **AI judges have biases.** They can be lenient on near-miss answers and may favour their own model family. Use a judge from a different provider when comparing providers.
- **Harnesses aren't apples to apples.** Hermes carries a lot of built-in scaffolding while LangGraph is minimal. A cost gap reflects that design choice, not just model efficiency.
