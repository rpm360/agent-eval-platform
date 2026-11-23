# 2. Pluggable Harness & Model Adapters

[← Back to Documentation Hub](./README.md) · [← System Architecture](./architecture.md)

A core design requirement of the platform is that **adding a new harness ($X$) or a new model ($Y$) means writing an adapter, not changing the platform core**. Both harnesses and models use auto-discovering plugin registries validated in [`tests/test_pluggable_adapters.py`](../tests/test_pluggable_adapters.py).

---

## 1. Harness Adapter Interface (`HarnessAdapter`)

Defined in [`eval_runner/agents/base.py`](../eval_runner/agents/base.py). Every harness adapter subclasses `HarnessAdapter` and registers itself with `@register_adapter`:

```python
class HarnessAdapter(ABC):
    name: str
    default_image: str

    def get_container_env(self, config: ConfigSpec, model: ModelEntry) -> dict[str, str]:
        """Return harness-specific environment variables (e.g. HERMES_HOME)."""
        return {}

    @abstractmethod
    def prepare_container(
        self,
        container: Container,
        task_dir: Path,
        instruction: str,
        config: ConfigSpec,
        model: ModelEntry,
        skills_root: Path,
    ) -> None:
        """Inject /io/spec.json, enabled skills, and optional seed MEMORY.md."""

    @abstractmethod
    def build_command(self, config: ConfigSpec, model: ModelEntry) -> list[str]:
        """Return argv list executed inside the container via exec_with_timeout."""

    def extract_outputs(
        self, container: Container
    ) -> tuple[dict[str, Any], list[TraceEvent]]:
        """Read /io/result.json and /io/trace.jsonl from the container after exit."""
```

### In-Container I/O Contract
Regardless of how an agent framework works internally (or what language it is written in), its in-container entrypoint follows a three-file contract:
1. **Input (`/io/spec.json`):** Contains `task_id`, `instruction`, `model_id`, `litellm_model`, `provider`, `api_base`, and `settings` (`temperature`, `max_steps`, `timeout_sec`, `memory`, `skills`, `tools`, `max_output_tokens`, `max_total_tokens`).
2. **Trajectory Output (`/io/trace.jsonl`):** Newline-delimited JSON objects matching the unified [`TraceEvent`](./data-model-and-isolation.md) schema.
3. **Summary Output (`/io/result.json`):** JSON object containing `{"status": "ok" | "infra_error" | "agent_error", "final_answer": "...", "steps": <int>, "input_tokens": <int>, "output_tokens": <int>}`.

---

## 2. Built-in Harness Implementations

### A. Hermes Agent (`hermes`)
- **Host Adapter:** [`eval_runner/agents/hermes.py`](../eval_runner/agents/hermes.py) (`default_image = "agent-eval-hermes:latest"`).
- **In-Container Runner:** [`eval_runner/agents/container_hermes.py`](../eval_runner/agents/container_hermes.py).
- **How it works:**
  - Wipes `/root/.hermes` before every trial so zero state leaks across runs.
  - When `settings.memory = True`, copies `tasks/<id>/seed/MEMORY.md` into `/root/.hermes/MEMORY.md` and logs a `memory_op` (`op: "read"`) event. After the session ends, diffs `MEMORY.md` and logs a `memory_op` (`op: "write"`) event if the agent updated its memory.
  - Copies only the skills listed in `settings.skills` into `/root/.hermes/skills/<skill_id>/SKILL.md` (clearing any unrequested skills).
  - Imports `AIAgent` from `/opt/hermes-agent/run_agent.py` and starts an in-process OpenAI-compatible **LiteLLM bridge** (`_litellm_openai_bridge` on `http://127.0.0.1:<port>/v1`) so Hermes reaches **all** models (Gemini, Claude, OpenRouter, Ollama, etc.) through the exact same common LiteLLM interface as LangGraph and LLM-as-judge—with zero provider-specific branching in `container_hermes.py` and no `hermes setup` requirement.
  - Invokes `agent.run_conversation(user_message=..., task_id=..., system_message=...)` and captures exact token usage (`input_tokens`, `output_tokens`) directly from the LiteLLM bridge.
  - Inspects Hermes's `final_response` and `error` fields for upstream provider errors (`404`, `429`, `401`, `503`) that Hermes catches internally, converting them into `status: "infra_error"` so provider outages are never scored as `0.0`.

### B. LangGraph ReAct Agent (`langgraph`)
- **Host Adapter:** [`eval_runner/agents/langgraph.py`](../eval_runner/agents/langgraph.py) (`default_image = "agent-eval-langgraph:latest"`).
- **In-Container Runner:** [`eval_runner/agents/container_langgraph.py`](../eval_runner/agents/container_langgraph.py).
- **How it works:**
  - Uses `langgraph.prebuilt.create_react_agent` paired with `ChatLiteLLM` (so any LiteLLM-supported provider works uniformly) and `SqliteSaver` (`/io/checkpoints.db`) for step-level state checkpointing.
  - Exposes workspace tools: `run_bash` (30s per-command timeout), `read_file`, `write_file`, and `list_dir`.
  - Dynamically registers `read_skill` when `settings.skills` is non-empty, and `read_memory` / `write_memory` (backed by `/agent-home/MEMORY.md`) when `settings.memory = True`.
  - Enforces `settings.tools` strictly by filtering the active tool list when a tool allow-list is configured.

---

## 3. How to Add a New Harness (Zero Core Edits)

`eval_runner/agents/base.py` automatically discovers:
1. Every Python module dropped into `eval_runner/agents/<name>.py`, and
2. Any installed Python package declaring an `agent_eval.harnesses` entry point in `pyproject.toml`.

**Example (`eval_runner/agents/smolagents_adapter.py`):**
```python
from pathlib import Path
from docker.models.containers import Container
from eval_runner.agents.base import HarnessAdapter, register_adapter
from eval_runner.container import put_files
from eval_runner.schemas import ConfigSpec, ModelEntry

@register_adapter
class SmolAgentsAdapter(HarnessAdapter):
    name = "smolagents"
    default_image = "agent-eval-smolagents:latest"

    def prepare_container(self, container: Container, task_dir: Path, instruction: str,
                          config: ConfigSpec, model: ModelEntry, skills_root: Path) -> None:
        put_files(container, "/io", {"spec.json": config.model_dump_json()})

    def build_command(self, config: ConfigSpec, model: ModelEntry) -> list[str]:
        return ["python3", "/opt/eval_agents/container_smolagents.py", "/io/spec.json"]
```
Once saved, `smolagents` immediately appears in `eval-run -H smolagents` and in the Web UI's harness selector without editing `schemas.py`, `runner.py`, or `agents/__init__.py`.

---

## 4. Model Adapter Interface (`ModelAdapter`) & LiteLLM Routing

Defined in [`eval_runner/models.py`](../eval_runner/models.py).

```python
class ModelAdapter(ABC):
    name: str

    @abstractmethod
    def build_container_env(self, model: ModelEntry) -> dict[str, str]:
        """Return provider API keys / base URLs to inject into the trial container."""

    @abstractmethod
    def complete(
        self,
        model: ModelEntry,
        messages: list[dict[str, Any]],
        temperature: float = 0.0,
        **kwargs: Any,
    ) -> tuple[str, int, int]:
        """Execute a completion (used by LLM-as-judge & calibration) and return (text, in_tok, out_tok)."""
```

### Two Ways to Specify Any Model
1. **Named Catalog Entries ([`models.yaml`](../models.yaml)):** Pre-configured entries with custom token pricing, fallback models, and `api_base`:
   - `gemini-flash` (`gemini/gemini-3.8-flash`, fallback `gemini/gemini-3.5-flash-lite`)
   - `gemini-pro` (`gemini/gemini-3.1-pro-preview`, fallback `gemini/gemini-3.8-flash`)
   - `claude-sonnet` (`anthropic/claude-sonnet-4-5`, fallback `anthropic/claude-haiku-4-5`)
   - `claude-haiku` (`anthropic/claude-haiku-4-5`)
   - `openrouter-qwen-coder` (`openrouter/qwen/qwen-2.5-coder-32b-instruct`)
   - `ollama-qwen-coder` (`ollama/qwen2.5-coder:7b` via `http://host.docker.internal:11434`, `requires_api_key: false`)
   - `mock` (`mock/scripted`, zero-cost deterministic mode for CI and smoke tests)
2. **Direct LiteLLM `provider/model` Strings (`resolve_model`):** You can pass *any* LiteLLM identifier directly on the CLI (`-m openai/gpt-4o-mini`, `-m openrouter/deepseek/deepseek-chat-v3-0324`, `-m ollama/llama3.2:3b`) or in the Web UI's custom model box without editing `models.yaml`. `resolve_model()` automatically infers the provider, environment key (`OPENAI_API_KEY`, `OPENROUTER_API_KEY`, etc.), and cost via `litellm.cost_per_token()`.

### Resilience: Key Rotation, Backoff & Fallbacks
`build_litellm_router()` constructs a `litellm.Router` wrapped in Tenacity (`wait_random_exponential(min=1, max=30)`, 4 attempts). If `<ENV_KEY>_2` (e.g., `GEMINI_API_KEY_2`) is set in `.env`, the router automatically rotates across keys on HTTP 429 rate limits and fails over to `model.fallback` if configured.

---

## Related Documents
- **Next:** [3. Data Model, Isolation & Reproducibility](./data-model-and-isolation.md)
- **Tasks & Judge Routing:** [4. Benchmark Tasks, Graders & Judge Calibration](./tasks-and-graders.md)
