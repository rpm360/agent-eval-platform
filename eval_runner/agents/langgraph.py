"""LangGraph harness adapter (with built-in SqliteSaver checkpointing)."""

from __future__ import annotations

from pathlib import Path

from docker.models.containers import Container

from eval_runner.agents._seed_utils import (
    read_enabled_skill_files,
    read_seed_memory_if_enabled,
    serialize_trial_spec,
)
from eval_runner.agents.base import HarnessAdapter, register_adapter
from eval_runner.container import put_files
from eval_runner.schemas import ConfigSpec, ModelEntry

AGENT_HOME_DIR = "/agent-home"
LANGGRAPH_ENTRYPOINT_SCRIPT = "/opt/eval_agents/container_langgraph.py"


@register_adapter
class LangGraphAdapter(HarnessAdapter):
    """Container adapter for LangGraph ReAct agent (`create_react_agent` + `SqliteSaver`)."""

    name = "langgraph"
    default_image = "agent-eval-langgraph:latest"

    def prepare_container(
        self,
        container: Container,
        task_dir: Path,
        instruction: str,
        config: ConfigSpec,
        model: ModelEntry,
        skills_root: Path,
    ) -> None:
        container.exec_run(["mkdir", "-p", "/io/skills", AGENT_HOME_DIR])

        seed_memory = read_seed_memory_if_enabled(task_dir, config.settings.memory)
        if seed_memory is not None:
            put_files(container, AGENT_HOME_DIR, {"MEMORY.md": seed_memory})

        io_files: dict[str, bytes | str] = {
            f"skills/{skill_id}.md": skill_markdown
            for skill_id, skill_markdown in read_enabled_skill_files(
                skills_root, config.settings.skills
            ).items()
        }
        io_files["spec.json"] = serialize_trial_spec(task_dir, instruction, config, model)
        put_files(container, "/io", io_files)

    def build_command(self, config: ConfigSpec, model: ModelEntry) -> list[str]:
        return ["python3", LANGGRAPH_ENTRYPOINT_SCRIPT, "/io/spec.json"]
