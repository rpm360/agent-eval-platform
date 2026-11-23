# Experiment Guide

[← Back to Docs](./README.md)

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

## Trusting the Judge

Five writing tasks are scored by an AI judge. Before relying on it, we compared it against 30 human-labelled answers. It agreed **93% of the time** (Cohen's κ ≈ 0.87, well above our 0.6 bar). Its two misses were borderline answers that it scored a little too generously.

---

## Honest Limits

- **Small samples mean wide error bars.** With fewer than ~10 tasks or fewer than 3 attempts per task, even a big gap may be labelled *noise*. The dashboard warns you when this applies.
- **Easy tasks can't separate strong agents.** If both sides score 100%, you learn about cost and speed, not about which agent is smarter.
- **AI judges have biases.** They can be lenient on near-miss answers and may favour their own model family. Use a judge from a different provider when comparing providers.
- **Harnesses aren't apples to apples.** Hermes carries a lot of built-in scaffolding while LangGraph is minimal. A cost gap reflects that design choice, not just model efficiency.
