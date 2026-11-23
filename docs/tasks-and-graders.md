# 4. Benchmark Tasks, Graders & Judge Calibration

[← Back to Documentation Hub](./README.md) · [← Data Model, Isolation & Reproducibility](./data-model-and-isolation.md)

Grading logic lives in [`eval_runner/graders.py`](../eval_runner/graders.py), judge calibration lives in [`eval_runner/calibration.py`](../eval_runner/calibration.py), and the 24-task benchmark suite lives under [`tasks/`](../tasks/).

---

## 1. The 24-Task Benchmark Suite (`tasks/`)

The repository ships with **24 tasks** (19 deterministic, 5 LLM-as-judge) across 7 categories, specifically designed to separate configurations along tool use, multi-step coding, persistent memory (`memory: true` vs. `false`), and procedural skills (`skills` enabled vs. disabled):

| Task ID | Category | Grader | Discriminates | Description |
| :--- | :--- | :--- | :--- | :--- |
| `calc-compound-interest` | `computation` | `deterministic` | `tool_use` | Compute compound interest accurately using Python/bash and write `answer.txt`. |
| `calc-loan-amortization` | `computation` | `deterministic` | `tool_use` | Compute a fixed-rate monthly mortgage payment and write `payment.txt`. |
| `code-add-type-validation` | `coding` | `deterministic` | `coding` | Add input validation (`TypeError`/`ValueError`) to a conversion function. |
| `code-fix-binary-search` | `coding` | `deterministic` | `coding` | Fix an off-by-one bug in `binary_search` so hidden `pytest` tests pass. |
| `code-fix-lru-cache` | `coding` | `deterministic` | `coding` | Fix the eviction bug in `lru.py` (`popitem(last=False)`) so hidden tests pass. |
| `code-fix-multi-file` | `coding` | `deterministic` | `coding`, `steps` | Fix two cooperating bugs across a multi-file package (`pricing` + `cart`). |
| `code-implement-roman` | `coding` | `deterministic` | `coding` | Implement `to_roman`/`from_roman` with validation against hidden `pytest` tests. |
| `data-csv-join` | `data` | `deterministic` | `tool_use` | Join `orders.csv` with `customers.csv` and compute total amounts per country. |
| `data-json-transform` | `data` | `deterministic` | `tool_use` | Filter active users from `users.json` and sort by signup date. |
| `data-log-error-counts` | `data` | `deterministic` | `tool_use`, `precision` | Count `ERROR`-level log lines per module while ignoring distractor lines. |
| `file-csv-aggregate` | `data` | `deterministic` | `tool_use` | Aggregate `sales.csv` by region and write `summary.json`. |
| `fs-find-largest-file` | `filesystem` | `deterministic` | `tool_use` | Find the largest file in a nested directory tree (including hidden directories). |
| `fs-normalize-filenames` | `filesystem` | `deterministic` | `tool_use` | Rename files to `snake_case` without altering file contents. |
| `mem-api-version-header` | `memory` | `deterministic` | `memory` | Recall the team's internal API base URL and version header from `MEMORY.md`. |
| `mem-db-table-naming` | `memory` | `deterministic` | `memory` | Recall the database table naming and audit-column convention from `MEMORY.md`. |
| `mem-deploy-convention` | `memory` | `deterministic` | `memory` | Recall the Kubernetes deployment target format (`<env>-<region>-<service>-v2`) from `MEMORY.md`. |
| `skill-changelog-entry` | `skill` | `deterministic` | `skills` | Apply the house [`changelog-format`](../skills/changelog-format/SKILL.md) skill to write `CHANGELOG.md`. |
| `skill-commit-message` | `skill` | `deterministic` | `skills` | Apply the house [`commit-message-format`](../skills/commit-message-format/SKILL.md) skill to write `COMMIT_MSG.txt`. |
| `skill-release-tag` | `skill` | `deterministic` | `skills` | Apply the house [`release-tag-format`](../skills/release-tag-format/SKILL.md) skill (`aep-rel-YYYYMMDD-<6sha>`) to write `TAG.txt`. |
| `judge-api-docs` | `writing` | `llm_judge` | `quality` | Write accurate README documentation for a token-bucket rate limiter. |
| `judge-code-review` | `coding` | `llm_judge` | `quality`, `coding` | Review a code diff and identify three planted defects (SQLi, password logging, bare `except`). |
| `judge-explain-bug` | `reasoning` | `llm_judge` | `quality` | Explain the root cause of a moving-average bug, the fix, and an edge case. |
| `judge-incident-postmortem` | `writing` | `llm_judge` | `quality` | Write a blameless postmortem from a raw incident timeline log. |
| `judge-support-reply` | `memory` | `llm_judge` | `memory`, `quality` | Draft a customer support reply adhering to the refund policy stored in `MEMORY.md`. |

---

## 2. Grader Design (`eval_runner/graders.py`)

### A. Deterministic Grader (`grade_deterministic`)
- **Anti-Tampering / Post-Agent Injection:** During agent execution, the `tasks/<id>/tests/` directory is **never** present inside the container. Only *after* the agent process exits does `grade_deterministic()` inject `tests/` into `/grader-tests` via `put_directory()` and run `bash /grader-tests/test.sh` with a 120-second timeout.
- **Hidden Unit Tests:** For coding tasks (e.g., `code-fix-lru-cache`), `test.sh` runs `pytest -q -o addopts="" --rootdir=/grader-tests /grader-tests/test_lru.py` against `/workspace`, preventing any agent-created `pytest.ini` or `conftest.py` in `/workspace` from hijacking test collection.
- **Partial Credit Support:** If `test.sh` writes `/grader-tests/reward.json` (`{"score": 0.5, "passed": false, "reasoning": "..."}`), `grade_deterministic()` uses that structured score; otherwise exit code `0` yields `score = 1.0, passed = True` and non-zero yields `score = 0.0, passed = False`.

### B. Artifact-Aware LLM-as-Judge (`grade_llm_judge`)
- **Workspace Artifact Extraction:** If `task.yaml` specifies `grader.artifacts: ["REVIEW.md"]`, `grade_llm_judge()` extracts each listed file from `/workspace/<path>` (capped at 8,000 chars). If any required artifact is missing, it immediately fails with `score = 0.0` without spending judge tokens.
- **Prompt-Injection Isolation:** Candidate outputs and workspace artifacts are wrapped in explicit XML delimiters (`<artifact path="...">...</artifact>`, `<candidate_answer>...</candidate_answer>`) with a system instruction directing the judge to ignore any instructions inside candidate blocks.
- **Deterministic Rubric Output & JSON Repair:** Calls the configured judge model (`task.grader.judge_model` or `JUDGE_MODEL` from `.env`, defaulting to `gemini-flash`) at `temperature = 0.0`, requesting structured JSON:
  ```json
  {
    "score": 0.85,
    "passed": true,
    "reasoning": "Concise explanation of rubric criteria met or missed.",
    "criteria": [{"name": "identifies_sqli", "met": true}]
  }
  ```
  If the judge returns malformed or markdown-fenced JSON that fails extraction, `grade_llm_judge()` performs one automatic repair turn before raising `InfraModelError`.

---

## 3. Judge Trustworthiness & Calibration (`eval_runner/calibration.py`)

To verify that the LLM judge can be trusted, [`calibration/judge_labels.jsonl`](../calibration/judge_labels.jsonl) contains **30 human-labelled calibration examples** spanning all 5 judge-graded tasks (`judge-api-docs`, `judge-code-review`, `judge-explain-bug`, `judge-incident-postmortem`, `judge-support-reply`), including clear passes, clear failures, and borderline partial-credit examples.

Running `uv run eval-calibrate --judge gemini-flash --repeats 3` (or clicking **Run Calibration** in the Web UI) evaluates each example 3 times to measure both **human agreement** and **self-consistency**:

### Live Calibration Results ([`results/calibration/gemini-flash_20261122_135429.json`](../results/calibration/gemini-flash_20261122_135429.json))

| Metric | Measured Value (`gemini-flash`) | Trust Threshold | Status |
| :--- | :--- | :--- | :--- |
| **Cohen's $\kappa$ (Binary Pass/Fail)** | **0.8667** | $\ge 0.60$ | Pass |
| **Binary Accuracy** | **93.33%** (28 / 30) | $\ge 80.0\%$ | Pass |
| **Precision / Recall** | **88.24% / 100.0%** (TP=15, FP=2, TN=13, FN=0) | — | — |
| **Continuous Score MAE** | **0.0722** | — | — |
| **Spearman Rank Correlation ($\rho$)** | **0.9329** | — | — |
| **3-Run Self-Agreement** | **96.67%** (29 / 30 identical across 3 runs) | — | — |
| **Overall Verdict** | **`TRUSTED`** | $\kappa \ge 0.6 \land \text{Acc} \ge 0.8$ | **TRUSTED** |

The only 2 disagreements (`review-06` and `support-06`) were intentionally borderline human labels (`human_score = 0.6`, just below the `0.7` pass threshold) where the judge explicitly noted the missing criterion in its reasoning but awarded `0.75` and `0.85` partial credit.

---

## 4. How to Add a New Task

Create a new directory `tasks/<your-task-id>/` with:
```text
tasks/<your-task-id>/
├── task.yaml          # category, description, discriminates, timeout_sec, grader spec
├── instruction.md     # prompt shown to the agent
├── fixtures/          # (optional) files copied into /workspace before the agent runs
├── seed/
│   └── MEMORY.md      # (optional) seeded into agent memory only when settings.memory = true
└── tests/
    └── test.sh        # (for deterministic grader) copied into /grader-tests after agent exit
```
Run `uv run pytest tests/test_tasks_lint.py` to validate that your new task's schema, instruction, and grader configuration conform to platform standards.

---

## Related Documents
- **Next:** [5. Statistical Engine & Failure Taxonomy](./statistics-and-failures.md)
- **Judge UI & CLI Commands:** [6. TypeScript API, Web UI & CLI Reference](./api-and-ui.md)
