"""Hermes Agent harness adapter."""

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

HERMES_HOME_DIR = "/root/.hermes"
HERMES_ENTRYPOINT_SCRIPT = "/opt/eval_agents/container_hermes.py"


@register_adapter
class HermesAdapter(HarnessAdapter):
    """Container adapter for NousResearch Hermes Agent (`AIAgent`)."""

    name = "hermes"
    default_image = "agent-eval-hermes:latest"

    def get_container_env(self, config: ConfigSpec, model: ModelEntry) -> dict[str, str]:
        return {"HERMES_HOME": HERMES_HOME_DIR}

    def prepare_container(
        self,
        container: Container,
        task_dir: Path,
        instruction: str,
        config: ConfigSpec,
        model: ModelEntry,
        skills_root: Path,
    ) -> None:
        # Clean HERMES_HOME so zero state leaks between trials
        container.exec_run(["rm", "-rf", HERMES_HOME_DIR])
        container.exec_run(["mkdir", "-p", f"{HERMES_HOME_DIR}/skills", "/io"])

        hermes_files: dict[str, bytes | str] = {}
        seed_memory = read_seed_memory_if_enabled(task_dir, config.settings.memory)
        if seed_memory is not None:
            hermes_files["MEMORY.md"] = seed_memory

        for skill_id, skill_markdown in read_enabled_skill_files(
            skills_root, config.settings.skills
        ).items():
            hermes_files[f"skills/{skill_id}/SKILL.md"] = skill_markdown

        if hermes_files:
            put_files(container, HERMES_HOME_DIR, hermes_files)

        spec_json = serialize_trial_spec(task_dir, instruction, config, model)
        put_files(container, "/io", {"spec.json": spec_json})

    def build_command(self, config: ConfigSpec, model: ModelEntry) -> list[str]:
        return ["python3", HERMES_ENTRYPOINT_SCRIPT, "/io/spec.json"]
