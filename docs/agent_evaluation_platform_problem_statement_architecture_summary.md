# Agent Evaluation Platform: Problem Statement & Architectural Notes

## 1. Problem Statement & Specification

We ship AI agents built from two parts: a **harness** (the loop, tools, skills, memory, prompting strategy) and a **model**. Either one can change at any time. We swap models, upgrade harnesses, add skills and turn on memory, and every change raises the same question: **did the agent get better, worse, or stay the same, and how sure are we?**

Build a platform that evaluates any harness ($X$) running with any model ($Y$) and answers that question with evidence.

*(Note: A beautiful UI is not a constraint — a functional UI is enough. A better product does earn brownie points.)*

### Harnesses and Models
* **Required harness:** Hermes Agent (`NousResearch/hermes-agent`), an open-source harness with skills, memory, and tools.
* **Second harness:** Add at least one more so we can see your abstraction holds. It can be a minimal baseline you write yourself (a plain tool-calling loop) or an existing framework (Claude Agent SDK, OpenAI Agents SDK, `smolagents`, LangGraph, and so on).
* **Models:** At least two models from different providers, or one open-weight model, reached through a common interface (e.g., OpenRouter, LiteLLM, or your own adapter).
* **Extensibility:** Adding a new harness or a new model should mean writing an adapter, not changing the platform core. Show this in the design.

### Core Functional Requirements
1. **Tasks and scoring:** Define a task set and how each task is scored. Support at least:
   * Deterministic graders (exact match, unit tests, state checks on a sandbox or file system);
   * Model-based graders (LLM-as-judge with a rubric).
2. **Judge trustworthiness:** Where a judge is used, show how you checked that it’s trustworthy (e.g., agreement with a small set of human-labelled examples).
3. **Configurations:** Define what’s being compared as $\text{harness} \times \text{model} \times \text{settings}$ (skills, memory, tools, temperature, step and token budgets). Configs are versioned so a past result can always be reproduced.
4. **Execution:**
   * Run every task under every config, with $N$ repeated trials per task, because agents are non-deterministic.
   * Runs are isolated: no state leaks between trials unless a memory setting explicitly says so.
   * Handle timeouts, rate limits, retries, and partial failures without corrupting results.
5. **Comparison with confidence:**
   * Show whether config A beats config B, and how confident we can be: confidence intervals and a suitable paired test (e.g., bootstrap or McNemar).
   * Report per-task deltas, not just one aggregate score.
   * Make it clear when a difference is just noise.
   * Report cost, latency, and token usage next to quality, so trade-offs are visible.
6. **Run inspection:** For any single trial, show the full trajectory: messages, tool calls and results, memory reads and writes, which skills were invoked, grader reasoning, and the final score. A user should be able to see why it passed or failed.
7. **Failure analysis (stretch):** Group failures into categories (wrong tool, hallucinated tool args, gave up early, loop or step exhaustion, grader disagreement), so a regression points to a cause.

### Technical & Operational Requirements
* **Stack:** TypeScript for the API and UI. Python is allowed for harness workers.
* **Local Execution:** Runs locally with one command (e.g., `docker compose up`), with API keys supplied through `.env`.
* **Benchmark Suite:** Includes a sample task set of at least 20 tasks with a mix of grader types. At least a few tasks should be able to tell configs apart (e.g., tasks where a skill or memory should help).
* **Persistence & Export:** Results are persisted and can be exported (JSON or CSV).
* **Assumptions:** Document every assumption you make.

### Deliverables
1. **Source code in a Git repository:** Production-grade, tested, with a `README` covering setup, how to add a task, how to add a harness, and how to add a model.
2. **Design document covering:**
   * The architecture;
   * The harness and model adapter interfaces;
   * The data model (tasks, configs, experiments, trials, traces);
   * How runs are isolated and reproduced;
   * Grader design and how graders were validated;
   * The statistical method, and how you chose $N$.
3. **Known limits:** Cover where the platform’s conclusions should not be trusted (e.g., task-set size, judge bias, contamination, and harness-specific quirks).
4. **Cost estimate:** Give the cost per experiment as a formula ($\text{tasks} \times \text{trials} \times \text{configs} \times \text{average tokens} \times \text{price}$), plus the actual spend from your experiment. Explain how you’d reduce cost (caching, early stopping, sampling).
5. **One real experiment** comparing two configurations that differ along a single meaningful axis (e.g., the same harness with two models, the same model in two harnesses, or Hermes with memory on vs. off). Include:
   * Your hypothesis;
   * Setup and number of trials ($N$);
   * Results with confidence intervals;
   * Two or three inspected trajectories that explain the difference;
   * Your conclusion.

### Evaluation Rubric
| Area | What We Look For |
| :--- | :--- |
| **Eval methodology** | Sound grading, valid statistics, honest handling of noise |
| **Abstraction** | Clean harness and model adapters; a new $X$ or $Y$ is a small change |
| **Observability** | Traces detailed enough to debug an agent |
| **Engineering quality** | Reliability, tests, reproducibility, clear code |
| **Judgment** | Sensible scope cuts, clearly stated assumptions and limits |

---

## 2. Open-Source Agent Evaluation Landscape (GitHub)

Open-source agent evaluation repositories on GitHub generally fall into three categories:

### A. True Execution & Sandboxed Agent Harnesses
* **[UKGovernmentBEIS/inspect_ai](https://github.com/UKGovernmentBEIS/inspect_ai)** (MIT) — Built by the UK AI Security Institute. Supports Docker sandboxes, bash/Python tool execution, multi-turn ReAct loops, bridged external agents (`sandbox_agent_bridge`), model-graded scoring, and structured trajectory logs. Pairs with **[UKGovernmentBEIS/inspect_evals](https://github.com/UKGovernmentBEIS/inspect_evals)**.
* **[sierra-research/tau2-bench](https://github.com/sierra-research/tau2-bench)** (MIT) — Evaluates tool-using agents in multi-turn environments with LLM-simulated users, mock databases, and policy rules.
* **[ServiceNow/AgentLab](https://github.com/ServiceNow/AgentLab)** — Ray-based harness built on BrowserGym for parallel web/UI agent evaluations.
* **[SWE-bench/SWE-bench](https://github.com/SWE-bench/SWE-bench)** — Standard Dockerized evaluation harness (`swebench.harness`) for coding agents using containerized patch application and unit tests.

### B. Trajectory, CI/CD & Harness-Agnostic Eval Frameworks
* **[confident-ai/deepeval](https://github.com/confident-ai/deepeval)** (Apache-2.0) — `pytest`-style framework with agent trajectory metrics (`TaskCompletion`, `StepEfficiency`, `PlanAdherence`, `ToolCorrectness`).
* **[promptfoo/promptfoo](https://github.com/promptfoo/promptfoo)** (MIT) — Local-first TypeScript CLI and GitHub Action for testing agents, repeat trials, and adversarial red-teaming.
* **[awslabs/agent-evaluation](https://github.com/awslabs/agent-evaluation)** (Apache-2.0) — Concurrent multi-turn conversation test runner with evaluator LLMs.

### C. Self-Hosted Observability + Eval Platforms
* **[langfuse/langfuse](https://github.com/langfuse/langfuse)** (MIT / OpenTelemetry-native) — Self-hostable trace tree viewer, dataset manager, and online/offline LLM-as-a-judge evaluator.
* **[comet-ml/opik](https://github.com/comet-ml/opik)** (Apache-2.0) — Self-hostable tracing, experiment tracking, and `pytest` CI integration.

---

## 3. Recommended Platform Architecture

Because no single off-the-shelf tool satisfies every constraint (TypeScript API/UI + Python harness workers + Hermes Agent + one-command Docker deployment + paired statistical significance testing), the optimal approach is a **hybrid architecture** using **`UKGovernmentBEIS/inspect_ai`** for sandboxed execution and grading inside the Python worker pool, controlled by a **TypeScript API, Statistical Engine, and React UI**.

### Why `inspect_ai` Fits Best

| Requirement | `UKGovernmentBEIS/inspect_ai` Coverage | Custom TypeScript / Platform Layer |
| :--- | :--- | :--- |
| **Harness Abstraction ($X$)** | `bridged_agent` and `sandbox_agent_bridge` wrap external agents (`NousResearch/hermes-agent`, baseline loop) and intercept model/tool calls. | TypeScript `HarnessAdapter` registry & versioned config schema ($\text{harness} \times \text{model} \times \text{settings}$). |
| **Model Abstraction ($Y$)** | Unified provider abstraction (OpenAI, Anthropic, Google, OpenRouter, LiteLLM, vLLM) with automatic model-call proxying. | Model catalog in TS API/UI with token pricing tables, temperature, and step/token budgets. |
| **Isolation & Reproducibility** | Native per-sample Docker sandboxes (`sandbox="docker"`) prevent state leaks between trials. | Immutable config hashing + `docker-compose.yml` single-command orchestration. |
| **Graders & Validation** | Python deterministic scorers (unit tests, filesystem assertions) + rubric-based LLM judges with reasoning traces. | Judge calibration module computing agreement / Cohen's $\kappa$ against human-labelled examples. |
| **Repeated Trials ($N$) & Retries** | Native `epochs=N`, exponential backoff for rate limits, timeouts, and structured `.eval` logs. | Persistent job queue (Postgres + Redis/BullMQ) handling partial failures without corrupting completed trials. |
| **Stats, CIs & Failure Taxonomy** | Outputs per-sample/per-epoch scores and token usage (`samples_df`), but lacks paired CIs/McNemar natively. | TypeScript statistical module (paired bootstrap CIs, McNemar's test, per-task $\Delta$, noise indicators) + failure categorization. |

### System Diagram

```text
┌─────────────────────────────────────────────────────────────────┐
│ TypeScript Frontend (Next.js / React)                           │
│ • Matrix Builder (Harness X × Model Y × Settings)               │
│ • Paired Comparison View (Bootstrap CIs, McNemar p-val, Δ/task) │
│ • Trajectory Inspector (Messages, Tools, Memory R/W, Skills)    │
│ • Judge Calibration & Failure Taxonomy Breakdown                │
└───────────────────────────────┬─────────────────────────────────┘
                                │ REST / SSE
┌───────────────────────────────▼─────────────────────────────────┐
│ TypeScript Control Plane (Fastify / Hono + Drizzle + Postgres)  │
│ • Versioned Config & Task Registry (JSON/CSV Export)            │
│ • Trial Scheduler & Retry Queue (BullMQ / Redis)                │
│ • Statistical Engine (Paired Bootstrap, McNemar, Cost/Token)    │
└───────────────────────────────┬─────────────────────────────────┘
                                │ Job Queue
┌───────────────────────────────▼─────────────────────────────────┐
│ Python Harness Worker (inspect_ai + Docker Socket)              │
│ • HarnessAdapter Interface:                                     │
│    1. HermesAdapter (wraps NousResearch/hermes-agent + memory)  │
│    2. BaselineLoopAdapter (minimal OpenAI/LiteLLM tool loop)    │
│ • ModelAdapter (LiteLLM / OpenRouter proxy)                     │
│ • Ephemeral Docker Sandboxes + Deterministic & Rubric Graders   │
└─────────────────────────────────────────────────────────────────┘
```

### Implementation Notes for `Hermes Agent`
1. **Stateless Mode (`memory = false`):** Mount a clean, ephemeral profile/storage directory per trial container so zero state leaks across runs.
2. **Stateful Mode (`memory = true`):** Mount a trial-scoped persistent profile volume across dependent task sequences while keeping independent $N$ trial cohorts isolated from one another.
3. **Unified Tracing:** Normalize Hermes session logs, skill invocations, and memory read/write operations alongside `inspect_ai` event logs into a single `TraceEvent` schema so every harness renders identically in the UI.