# 5. Statistical Methodology, Choosing $N$ & Failure Taxonomy

[← Back to Documentation Hub](./README.md) · [← Benchmark Tasks, Graders & Judge Calibration](./tasks-and-graders.md)

The statistical engine lives in [`eval_runner/stats.py`](../eval_runner/stats.py) and the deterministic failure classifier lives in [`eval_runner/failures.py`](../eval_runner/failures.py).

---

## 1. Statistical Comparison Methodology (`eval_runner/stats.py`)

Because agent runs are stochastic and benchmark tasks vary widely in difficulty, comparing two configurations $A$ and $B$ requires **paired, task-level statistical inference** that accounts for both task-to-task correlation and within-task trial variance.

### Step 1: Filtering & Task-Level Pairing
1. **Exclude Infrastructure Failures:** Only trials with `status == "completed"` and a non-null `score` are included in statistical aggregates. Trials with `status == "infra_error"` are counted separately in `infra_errors` so network/rate-limit glitches never bias a configuration's mean score downward.
2. **Per-Task Mean Scores:** For each shared task $t \in \{1, \dots, T\}$ completed by both $A$ and $B$, we compute the mean task score across its $N$ repeated trials:
   $$\hat{s}_{A,t} = \frac{1}{N_{A,t}} \sum_{i=1}^{N_{A,t}} s_{A,t,i}, \qquad \hat{s}_{B,t} = \frac{1}{N_{B,t}} \sum_{i=1}^{N_{B,t}} s_{B,t,i}$$
3. **Paired Per-Task Delta:**
   $$d_t = \hat{s}_{B,t} - \hat{s}_{A,t}, \qquad \hat{\Delta} = \frac{1}{T} \sum_{t=1}^{T} d_t$$

### Step 2: Paired Bootstrap 95% Confidence Interval
- `paired_bootstrap_ci(deltas, confidence_level=0.95, n_resamples=10_000, seed=42)` resamples the paired task deltas $(d_1, \dots, d_T)$ with replacement $B = 10{,}000$ times using `scipy.stats.bootstrap` (`method="percentile"`).
- Using paired task deltas removes the between-task difficulty baseline (where easy tasks score $1.0$ on both configs and hard tasks score $0.0$ on both), isolating the true configuration difference.
- Within each individual task $t$, `compare_configs()` also computes a per-task bootstrap 95% CI across the paired trial differences $s_{B,t,i} - s_{A,t,i}$ and flags the task with `is_noise = True` whenever $0 \in [\text{CI}_{\text{low}, t}, \text{CI}_{\text{high}, t}]$.

### Step 3: Exact Two-Sided Binomial McNemar's Test
- For each shared task $t$, we determine majority pass/fail: $M_{A,t} = \mathbb{I}(\hat{s}_{A,t} \ge 0.5)$ and $M_{B,t} = \mathbb{I}(\hat{s}_{B,t} \ge 0.5)$.
- Let $n_{01}$ be the number of tasks where $A$ failed and $B$ passed, and $n_{10}$ be the number of tasks where $A$ passed and $B$ failed.
- `exact_mcnemar_pvalue()` computes the exact two-sided binomial $p$-value on the discordant pairs via `scipy.stats.binomtest(min(n_10, n_01), n_10 + n_01, p=0.5)`. (When $n_{10} + n_{01} = 0$, $p = 1.0$.)

### Step 4: Noise Detection & Automated Power Warnings
- **Verdict Rule:** If $0 \in [\text{CI}_{\text{low}}, \text{CI}_{\text{high}}]$, the comparison returns `verdict = "NOISE"`. Only when the 95% CI strictly excludes $0$ does the platform declare `"<Config B> BETTER"` or `"<Config A> BETTER"`.
- **Guardrail Warnings (`power_warnings`):** Automatically attaches warnings to the report when:
  - `shared_tasks < 10`: *"Low task count: paired bootstrap CI has wide uncertainty."*
  - $\min(n_{A,t}, n_{B,t}) < 3$: *"Low trial count per task: single-trial variance may dominate."*
  - All shared tasks are saturated (both $1.0$ or both $0.0$): *"All shared tasks are saturated — zero discriminating signal."*
  - `infra_errors / total > 10%`: *"High infra_error rate: run `eval-retry` before trusting results."*

---

## 2. How to Choose $N$ (Repeated Trials per Task)

The variance of the paired estimator $\hat{\Delta}$ over $T$ tasks and $N$ trials per task decomposes into:
$$\mathrm{Var}(\hat{\Delta}) = \frac{1}{T}\left(\sigma^2_{\text{between-tasks}} + \frac{\sigma^2_{\text{within-task}, A} + \sigma^2_{\text{within-task}, B}}{N}\right)$$

From this decomposition:
1. **$N = 1$ (Smoke / Sanity Runs):** Fast and cheap for verifying harness adapters and deterministic tasks at low temperature (`temperature = 0.2`), where within-task variance $\sigma^2_{\text{within}}$ is small.
2. **$N = 3$ to $5$ (Standard Evaluation):** Recommended for production comparisons. At `temperature = 0.2`, $N = 3\text{--}5$ reduces the within-task variance contribution $\sigma^2_{\text{within}} / N$ below 25% of total variance; beyond $N = 5$, adding more **tasks ($T$)** increases statistical power much faster than adding more trials ($N$).

---

## 3. Quality vs. Cost vs. Latency Trade-Off Metrics

Alongside quality (`mean_score`, `pass_rate`), `summarize_config()` reports:
- **Cost:** `avg_cost_usd` per trial, `total_cost_usd`, and **`cost_per_pass_usd`** ($\text{total\_cost\_usd} / \text{n\_passed}$, measuring the real dollar cost per successfully solved task).
- **Latency:** `avg_runtime_sec`, median **`p50_runtime_sec`**, and tail **`p95_runtime_sec`**.
- **Token Footprint:** `avg_tokens` (`input_tokens + output_tokens`).

---

## 4. Rule-Based Failure Taxonomy (`eval_runner/failures.py`)

Every failed or errored trial is automatically classified by `classify_failure()` into one of **12 deterministic categories**, evaluated in strict precedence order so root causes (e.g., an infinite tool loop or token budget cutoff) are never masked by downstream symptoms:

| Precedence | Category | Trigger Condition |
| :---: | :--- | :--- |
| 1 | `infra_error` | `trial.status == "infra_error"` (provider 429/5xx exhaustion, 401/404, Docker/runner error). |
| 2 | `budget_exhausted` | `input_tokens + output_tokens > settings.max_total_tokens`. |
| 3 | `timeout` | Agent exceeded `min(settings.timeout_sec, task.timeout_sec)` and was killed by watchdog. |
| 4 | `step_exhaustion` | `trial.steps >= settings.max_steps` or trace contains `recursion_limit` / `max_iterations`. |
| 5 | `loop` | $\ge 3$ consecutive `tool_call` events with identical `(tool_name, normalized_args)`. |
| 6 | `hallucinated_tool_args` | `tool_result` contains `file not found`, `no such file`, `invalid argument`, `jsondecodeerror`, or `unknown skill`. |
| 7 | `wrong_tool` | Agent invoked a tool outside `settings.tools` allow-list or received `unknown tool`. |
| 8 | `missed_memory` | Task discriminates `memory`, but trace contains no `memory_op(op="read")` event. |
| 9 | `missed_skill` | Task discriminates `skills`, but trace contains no `skill_invoked` event. |
| 10 | `gave_up_early` | Agent made $0$ tool calls or refused (`"i cannot"`, `"unable to"`, `"i do not have access"`). |
| 11 | `grader_borderline` | `llm_judge` graded trial failed, but $|\text{score} - \text{pass\_threshold}| \le 0.10$. |
| 12 | `wrong_output` | Agent completed normally using tools, but its final answer or workspace state failed verification. |

Running `uv run eval-failures --exp <id>` (or viewing the **Failure Breakdown** panel in the Web UI) groups failures by category per config, provides clickable example trial IDs, and computes per-category regression deltas ($\text{Count}_B - \text{Count}_A$).

---

## Related Documents
- **Next:** [6. TypeScript API, Web UI & CLI Reference](./api-and-ui.md)
- **Empirical Failure & Trajectory Examples:** [8. Real Experiment Report & Trajectories](./experiments.md)
