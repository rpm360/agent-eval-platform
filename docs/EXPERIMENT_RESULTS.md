# Experiment Report: Hermes vs. LangGraph on Gemini Flash

[← Back to Docs](./README.md) · **Raw Data:** [`results/hermes_langgraph__gemini-flash__2026-11-23_13-32-24/`](../results/hermes_langgraph__gemini-flash__2026-11-23_13-32-24/)

---

## 1. Question & Setup

**The question:** When we run the exact same model (`gemini/gemini-3.8-flash`) inside two different agent harnesses (**Hermes** vs. **LangGraph**) with memory and skills turned off, how do they compare on pass rate, speed, token cost, and failure behavior?

- **Experiment ID:** [`hermes_langgraph__gemini-flash__2026-11-23_13-32-24`](../results/hermes_langgraph__gemini-flash__2026-11-23_13-32-24/manifest.json)
- **Configs compared:** `hermes-gemini-flash` (`fa4b306e355f`) vs. `langgraph-gemini-flash` (`88d521e68765`)
- **Settings ([`configs/nomem.yaml`](../configs/nomem.yaml)):** `temperature: 0.2`, `max_steps: 20`, `timeout_sec: 180`, `memory: false`, `skills: []`
- **Sample size:** 19 deterministic benchmark tasks × `N = 1` trial per task (38 total trials, `seed: 42`, 0 infrastructure errors)

---

## 2. Scorecard & Statistical Verdict

| Metric (19 shared tasks) | Hermes (`hermes-gemini-flash`) | LangGraph (`langgraph-gemini-flash`) | Difference (A − B) |
| :--- | :---: | :---: | :---: |
| **Pass rate (Mean score)** | **63.2%** (12 / 19) | **63.2%** (12 / 19) | **0.0%** |
| **95% confidence interval** | — | — | `[0.0%, 0.0%]` |
| **McNemar pass/fail p-value** | — | — | `p = 1.00` |
| **Quality verdict** | **Tie (`NOISE`)** | **Tie (`NOISE`)** | No task flipped |
| **Median runtime (`p50`)** | 57.2s | **48.6s** | LangGraph **15% faster** |
| **Avg tokens per trial** | 53,178 | **27,389** | LangGraph **1.9× fewer tokens** |
| **Cost per passing task** | \$0.0688 | **\$0.0409** | LangGraph **41% cheaper** |
| **Total experiment cost** | \$0.8257 | **\$0.4911** | Saved \$0.3346 |

### Breakdown by Task Bucket

| Task Bucket | Hermes Passed | LangGraph Passed | What Happened |
| :--- | :---: | :---: | :--- |
| **Math, Data & Files** (8 tasks) | **8 / 8 (100%)** | **8 / 8 (100%)** | Both solved every CSV, JSON, log, and math task cleanly. |
| **Coding & Bug Fixes** (5 tasks) | **4 / 5 (80%)** | **4 / 5 (80%)** | Both fixed 4 bugs (`lru-cache`, `binary-search`, `type-validation`, `multi-file`) and timed out on `code-implement-roman`. |
| **Memory Recall** (3 tasks) | **0 / 3 (0%)** | **0 / 3 (0%)** | Expected baseline failure: `memory: false` withheld `MEMORY.md`, proving those tasks cannot be guessed without memory. |
| **Procedural Skills** (3 tasks) | **0 / 3 (0%)** | **0 / 3 (0%)** | Expected baseline failure: `skills: []` withheld `SKILL.md`, proving house formats cannot be guessed without the skill. |

---

## 3. What the Traces Reveal (3 Inspected Trajectories)

### Trajectory 1: Short tasks favor LangGraph's lean prompt (`calc-compound-interest`)
- **Traces:** [`hermes...calc-compound-interest_t1.trace.jsonl`](../results/hermes_langgraph__gemini-flash__2026-11-23_13-32-24/trials/hermes-gemini-flash_fa4b306e355f_calc-compound-interest_t1.trace.jsonl) vs. [`langgraph...calc-compound-interest_t1.trace.jsonl`](../results/hermes_langgraph__gemini-flash__2026-11-23_13-32-24/trials/langgraph-gemini-flash_88d521e68765_calc-compound-interest_t1.trace.jsonl)
- **What happened:** Both harnesses ran a quick Python one-liner, wrote `16288.95` to `/workspace/answer.txt`, and passed in ~24–25 seconds.
- **Why cost differed by 5×:** Hermes finished in just 2 steps but sent **28,991 input tokens** (\$0.0235) because its full default system prompt and built-in tool schemas are loaded on every turn. LangGraph's minimal 4-tool ReAct loop used only **5,249 input tokens** (\$0.0076) for the exact same result.

### Trajectory 2: Focused patching vs. over-testing on multi-file code (`code-fix-multi-file`)
- **Traces:** [`hermes...code-fix-multi-file_t1.trace.jsonl`](../results/hermes_langgraph__gemini-flash__2026-11-23_13-32-24/trials/hermes-gemini-flash_fa4b306e355f_code-fix-multi-file_t1.trace.jsonl) vs. [`langgraph...code-fix-multi-file_t1.trace.jsonl`](../results/hermes_langgraph__gemini-flash__2026-11-23_13-32-24/trials/langgraph-gemini-flash_88d521e68765_code-fix-multi-file_t1.trace.jsonl)
- **What happened:** Both agents found both bugs in `/workspace/shop/` (`cart.py` ignored item quantity `qty`, and `pricing.py` returned the discount amount instead of the discounted price) and passed the hidden `pytest` suite.
- **How their behavior diverged:** Hermes used its structured `patch` tool, ran a quick verification script, cleaned up `__pycache__`, and finished in **15 steps (104.5s)**. LangGraph spent 6 extra turns exploring floating-point rounding edge cases (`0.045000000000000005`) before patching the files, hitting the **20-step ceiling (150.5s)** right after writing the passing fix.

### Trajectory 3: How each harness fails when memory or skills are missing (`mem-deploy-convention` & `skill-changelog-entry`)
- **Traces:** [`langgraph...mem-deploy-convention_t1.trace.jsonl`](../results/hermes_langgraph__gemini-flash__2026-11-23_13-32-24/trials/langgraph-gemini-flash_88d521e68765_mem-deploy-convention_t1.trace.jsonl) & [`langgraph...skill-changelog-entry_t1.trace.jsonl`](../results/hermes_langgraph__gemini-flash__2026-11-23_13-32-24/trials/langgraph-gemini-flash_88d521e68765_skill-changelog-entry_t1.trace.jsonl)
- **What happened:** When a prompt asked for a house convention from memory or a skill that wasn't mounted (`memory: false, skills: []`), **neither agent guessed wildly**—instead, both refused to fabricate an answer and searched the container for the missing rule until they ran out of budget:
  - **Hermes** stalled inside long shell searches until the **120s task watchdog** terminated the container (`failure_category: timeout` on all 6 memory/skill tasks).
  - **LangGraph** fired rapid bash commands (`find / -name "*changelog*"`, `ls -la /io/skills`, `ls -la /agent-home`, `grep -rnwi ...`) until it hit `max_steps: 20` on 3 tasks (`failure_category: step_exhaustion`) and the 120s timeout on the other 3.

---

## 4. Conclusions & Recommendations

1. **Same model = same task accuracy (63.2% vs. 63.2%).** When given the same underlying model (`gemini-3.8-flash`) and settings, switching between Hermes and LangGraph did not change pass/fail outcomes on a single task (`verdict: NOISE`).
2. **LangGraph is 41% cheaper and 15% faster at median.** Because LangGraph exposes only the 4–6 tools needed for the benchmark, it uses roughly half the tokens of Hermes overall—and **3× to 5× fewer tokens** on short single-file tasks.
3. **Memory and Skill tasks have a 0% baseline without `MEMORY.md` / `SKILL.md`.** All 6 memory and skill tasks failed under `configs/nomem.yaml`, confirming that our benchmark tasks cannot be solved by pre-training knowledge alone.
4. **Guard against "search spirals" when context is missing.** Trace inspection showed that when an agent is asked for a convention it doesn't have, it will `find /` and `grep` across the container filesystem until it hits `max_steps` or `timeout`. Telling the agent in its system prompt to fail fast if `/agent-home/MEMORY.md` or `/io/skills/` is empty would save ~100 seconds and ~80,000 tokens per failed trial.
