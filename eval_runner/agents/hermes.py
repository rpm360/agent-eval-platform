"""Hermes Agent harness adapter."""

from __future__ import annotations

import json
from pathlib import Path

from docker.models.containers import Container

from eval_runner.agents.base import HarnessAdapter, register_adapter
from eval_runner.container import put_files
from eval_runner.schemas import ConfigSpec, ModelEntry


@register_adapter
class HermesAdapter(HarnessAdapter):
    name = "hermes"
    default_image = "agent-eval-hermes:latest"

    def get_container_env(self, config: ConfigSpec, model: ModelEntry) -> dict[str, str]:
        return {"HERMES_HOME": "/root/.hermes"}

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
        container.exec_run(["rm", "-rf", "/root/.hermes"])
        container.exec_run(["mkdir", "-p", "/root/.hermes/skills", "/io"])

        hermes_files: dict[str, bytes | str] = {}

        # Seed MEMORY.md only when memory is enabled (supports harness-agnostic seed/ or legacy seed_hermes/)
        seed_mem = task_dir / "seed" / "MEMORY.md"
        if not seed_mem.exists():
            seed_mem = task_dir / "seed_hermes" / "MEMORY.md"
        if config.settings.memory and seed_mem.exists():
            hermes_files["MEMORY.md"] = seed_mem.read_text(encoding="utf-8")

        # Copy only explicitly enabled skills
        for skill_id in config.settings.skills:
            skill_file = skills_root / skill_id / "SKILL.md"
            if skill_file.exists():
                hermes_files[f"skills/{skill_id}/SKILL.md"] = skill_file.read_text(
                    encoding="utf-8"
                )

        if hermes_files:
            put_files(container, "/root/.hermes", hermes_files)

        spec = {
            "task_id": task_dir.name,
            "instruction": instruction,
            "model_id": model.id,
            "litellm_model": model.litellm,
            "provider": model.provider,
            "api_base": model.api_base,
            "settings": config.settings.model_dump(mode="json"),
        }
        put_files(container, "/io", {"spec.json": json.dumps(spec, indent=2)})

    def build_command(self, config: ConfigSpec, model: ModelEntry) -> list[str]:
        return ["python3", "/opt/eval_agents/container_hermes.py", "/io/spec.json"]
