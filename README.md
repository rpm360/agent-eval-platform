# Agent Evaluation Platform

A local platform to test and compare AI agents (**Hermes** and **LangGraph**) across different **AI models** (Gemini, Claude, OpenRouter, vLLM, Ollama) and see which setup works better, faster, and cheaper.

---

## 1. Setup

**What you need installed:** [Docker Desktop](https://www.docker.com/products/docker-desktop/) (make sure it is open and running).

1. **Copy the example environment file and add your API key(s):**
   ```bash
   cp .env.example .env
   ```
   Open `.env` and paste your key (for example `GEMINI_API_KEY=...` or `ANTHROPIC_API_KEY=...`).

2. **Start the platform:**
   ```bash
   docker compose up
   ```
   *(The first run takes a few minutes to build the containers.)*

3. **Open the dashboard:**
   Go to **http://localhost:3000** in your browser. From there you can pick your harnesses, models, and tasks, click **Run Experiment**, and watch results stream in live.

*(To run the automated tests locally: `uv run pytest -v` and `cd api && npm test`.)*

---

## 2. How to Add a Task

1. Create a new folder inside `tasks/` (for example `tasks/my-task/`).
2. Add these files inside it:
   - `instruction.md` — the prompt telling the agent what to do.
   - `task.yaml` — basic settings and how to grade it:
     ```yaml
     id: my-task
     category: coding
     grader:
       type: deterministic
       script: tests/test.sh
     ```
   - `tests/test.sh` — a script that exits with `0` if the agent passed, or non-zero if it failed.
   - `fixtures/` *(optional)* — any starter files the agent needs in its workspace.
   - `seed/MEMORY.md` *(optional)* — memory notes given to the agent when memory is turned on.

---

## 3. How to Add a Harness

1. Create a new Python file in `eval_runner/agents/` (for example `eval_runner/agents/my_harness.py`).
2. Subclass `HarnessAdapter` and add `@register_adapter` above your class:
   ```python
   from eval_runner.agents.base import HarnessAdapter, register_adapter

   @register_adapter
   class MyHarnessAdapter(HarnessAdapter):
       name = "my-harness"
       default_image = "agent-eval-my-harness:latest"

       def prepare_container(self, container, task_dir, instruction, config, model, skills_root):
           # Copy /io/spec.json into the container
           ...

       def build_command(self, config, model):
           return ["python3", "/opt/eval_agents/run.py", "/io/spec.json"]
   ```
3. Restart the app (`docker compose up --build`)—your new harness appears automatically in the UI and CLI.

---

## 4. How to Add a Model

- **Easiest way:** Open [`models.yaml`](models.yaml) and add a new entry:
  ```yaml
  - id: my-model
    litellm: openai/gpt-4o-mini
    provider: openai
    env_key: OPENAI_API_KEY
    pricing:
      input_per_mtok: 0.15
      output_per_mtok: 0.60
  ```
  *(For self-hosted vLLM or Ollama models that don't need an API key, set `api_base: https://your-endpoint/v1` and `requires_api_key: false`.)*

- **Quick one-off test:** You can also type any LiteLLM `provider/model` name directly into the custom model box in the Web UI without editing `models.yaml`.

---

More details (architecture, statistics, grader calibration, and experiment reports) are in [`docs/`](docs/README.md).
