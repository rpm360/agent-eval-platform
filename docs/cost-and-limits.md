# 7. Cost Model, Assumptions & Known Limits

[← Back to Documentation Hub](./README.md) · [← TypeScript API, Web UI & CLI Reference](./api-and-ui.md)

This document covers the analytical cost formula, actual spend from our live experiments, strategies for reducing evaluation cost, and the explicit assumptions and statistical boundaries where platform conclusions should **not** be over-interpreted.

---

## 1. Cost Formula & Actual Experiment Spend

### Analytical Cost Formula
For an experiment comparing $C$ configurations across $T$ tasks (of which $T_{\text{judge}}$ use the LLM-as-judge grader) with $N$ repeated trials per task:

$$\text{Total Cost (USD)} = \underbrace{\sum_{c=1}^{C} T \cdot N \cdot \left(\frac{\bar{t}_{\text{in}, c}}{10^6} p_{\text{in}, c} + \frac{\bar{t}_{\text{out}, c}}{10^6} p_{\text{out}, c}\right)}_{\text{Agent Execution Cost}} + \underbrace{C \cdot T_{\text{judge}} \cdot N \cdot \left(\frac{\bar{t}_{\text{in, judge}}}{10^6} p_{\text{in, judge}} + \frac{\bar{t}_{\text{out, judge}}}{10^6} p_{\text{out, judge}}\right)}_{\text{LLM-as-Judge Cost}}$$

Where:
- $\bar{t}_{\text{in}, c}, \bar{t}_{\text{out}, c}$ are the average input and output tokens per trial under configuration $c$.
- $p_{\text{in}, c}, p_{\text{out}, c}$ are the model's input and output prices per $10^6$ tokens (looked up from [`models.yaml`](../models.yaml) or fallback `litellm.cost_per_token()`).

### Observed Token Footprint & Actual Spend (`results/`)
Because **Hermes Agent** injects a rich built-in system prompt and multi-toolset schema on every turn, its input token footprint per trial is roughly $4\times\text{--}5\times$ larger than the minimal **LangGraph** ReAct loop:

| Experiment / Run | Configuration | Model (`litellm`) | Trials | Avg Tokens / Trial | Avg Cost / Trial | Recorded Total Spend |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: |
| `verify_v3` | `hermes-gemini-flash` | `gemini/gemini-3.8-flash` | 1 | 22,939 | \$0.01893 | \$0.01893 |
| `verify_v3` | `langgraph-gemini-flash` | `gemini/gemini-3.8-flash` | 1 | 3,441 | \$0.00411 | \$0.00411 |
| `exp_20261122_141515` | `hermes-gemini-flash` | `gemini/gemini-3.8-flash` | 1 | 19,606 | \$0.01971 | \$0.01971 |
| `exp_20261122_141515` | `langgraph-gemini-flash` | `gemini/gemini-3.8-flash` | 1 | 15,351 | \$0.01838 | \$0.01838 |
| `hermes_mem_on` | `hermes-gemini-flash` | `gemini/gemini-3.8-flash` | 3 | 22,109 | \$0.01961 | \$0.05884 |
| `today test` | `hermes-gemini-pro` | `gemini/gemini-3.1-pro-preview` | 2 | 18,484 | \$0.03368 | \$0.06737 |
| `gemini-pro` | `langgraph-gemini-pro` | `gemini/gemini-3.1-pro-preview` | 10 | 3,270 | \$0.00889 | \$0.08891 |
| `calibration` | `gemini-flash` (Judge) | `gemini/gemini-3.8-flash` | $30 \times 3 = 90$ | ~1,100 | ~\$0.00110 | ~\$0.09900 |

- **Projected Full 24-Task Benchmark Cost ($T=24, N=3, C=2$ on `gemini-flash`):**
  - Hermes arm ($72$ trials $\times \sim\$0.0195$): **~\$1.40**
  - LangGraph arm ($72$ trials $\times \sim\$0.0080$): **~\$0.58**
  - LLM-as-Judge ($5 \text{ judge tasks} \times 3 \times 2 = 30 \text{ calls} \times \sim\$0.0011$): **~\$0.03**
  - **Total per 2-config full benchmark run:** **~\$2.01**

### Strategies to Reduce Evaluation Cost
1. **Zero-Cost Mock Tier (`-m mock`):** All CI tests, container lifecycle checks, and task verifier sanity checks run against `MockModelAdapter` at **\$0.00**.
2. **Tiered Model Selection & Judge Offloading:** Use a fast, low-cost calibrated model (`gemini-flash` or `gemini-3.5-flash-lite`) as `JUDGE_MODEL` even when evaluating frontier models (`gemini-pro`, `claude-sonnet`).
3. **Selective Retry (`eval-retry`):** Atomic per-trial persistence ensures transient rate-limit failures never require re-running already-completed trials.
4. **Token Budgets (`Settings.max_total_tokens` & `max_output_tokens`):** Caps runaway reasoning loops and immediately classifies over-budget trials as `budget_exhausted`.
5. **Staged Filtering (Discriminating Subsets First):** Run targeted subsets (e.g., `--tasks tasks/mem-deploy-convention` or category subsets at $N=1$) before scaling to $T=24, N=5$.

---

## 2. Documented Assumptions

1. **Host Docker Socket Access:** Both local CLI runs and `docker compose up` assume access to `/var/run/docker.sock` to spawn sibling containers from `agent-eval-hermes:latest` and `agent-eval-langgraph:latest`.
2. **Trial-Scoped Seeded Memory:** To preserve trial independence and allow parallel execution across $N$ trials, `settings.memory = True` seeds `tasks/<id>/seed/MEMORY.md` into the container at the start of the trial rather than carrying state over from unrelated prior tasks.
3. **File-Backed Persistence:** Trial records (`.json`), trajectories (`.trace.jsonl`), and experiment manifests (`manifest.json`) are stored as atomic files under `results/` rather than requiring an external Postgres/Redis server.
4. **Calibrated Judge Baseline:** The 30 labels in `calibration/judge_labels.jsonl` serve as the reference standard for `eval-calibrate`. Teams deploying custom tasks should append their own domain-specific human labels before relying on `TRUSTED` verdicts.

---

## 3. Known Limits (Where Conclusions Should *Not* Be Trusted)

1. **Statistical Power on Small $T$ or Small $N$:**
   - With $T < 10$ tasks or $N < 3$ trials per task, paired bootstrap CIs are wide and exact McNemar's test has low statistical power (for example, on 5 tasks, even a 5-0 discordant split yields $p = 0.0625 > 0.05$). The platform explicitly emits `power_warnings()` in these regimes.
2. **Task Saturation (Ceiling / Floor Effects):**
   - When comparing two strong configurations on tasks where both achieve $100\%$ pass rate (such as `hermes-gemini-pro` vs. `langgraph-gemini-pro` on the 5 starter tasks, where both scored $10/10$), the quality delta is $0.0$ (`NOISE`). In saturated regimes, conclusions can only be drawn on **efficiency trade-offs** (cost, token usage, latency), not capability ceilings.
3. **LLM-as-Judge Bias & Self-Preference:**
   - Even with $\kappa = 0.8667$, LLM judges exhibit leniency on borderline partial-credit answers (as seen in `review-06` and `support-06`, where the judge noticed the missing criterion in prose but still awarded $\ge 0.75$). Furthermore, using a Gemini judge to compare a Gemini agent against a Claude agent risks family self-preference bias; cross-family judging or an ensemble judge should be used for cross-provider benchmarks.
4. **Harness Architectural Asymmetry:**
   - Hermes Agent runs its own internal prompt framing, progressive-disclosure skill loader, and toolset manager, whereas LangGraph runs a minimal `create_react_agent` loop. A higher token cost on Hermes reflects its general-purpose agent scaffolding rather than raw model inefficiency.
5. **Network Access Inside Trial Containers:**
   - Trial containers need outbound HTTPS access to call model provider APIs (`generativelanguage.googleapis.com`, `api.anthropic.com`, `openrouter.ai`). A malicious or hallucinating agent could theoretically issue outbound network requests via `bash` during a trial unless restricted by an outbound firewall/proxy.

---

## Related Documents
- **Next:** [8. Real Experiment Report & Trajectories](./experiments.md)
- **Statistical Formulas:** [5. Statistical Engine & Failure Taxonomy](./statistics-and-failures.md)
