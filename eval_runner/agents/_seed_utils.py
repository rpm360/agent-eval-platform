"""Shared task-seeding and `/io/spec.json` helpers for host-side harness adapters."""

from __future__ import annotations

import json
from pathlib import Path

from eval_runner.schemas import ConfigSpec, ModelEntry


def read_seed_memory_if_enabled(task_dir: Path, memory_enabled: bool) -> str | None:
    """Return task `MEMORY.md` contents when `settings.memory` is enabled (supporting legacy `seed_hermes/`)."""
    if not memory_enabled:
        return None
    seed_memory_path = task_dir / "seed" / "MEMORY.md"
    if not seed_memory_path.exists():
        seed_memory_path = task_dir / "seed_hermes" / "MEMORY.md"
    if not seed_memory_path.exists():
        return None
    return seed_memory_path.read_text(encoding="utf-8")


def read_enabled_skill_files(skills_root: Path, enabled_skills: list[str]) -> dict[str, str]:
    """Read `SKILL.md` contents keyed by `skill_id` for all explicitly enabled skills."""
    loaded_skills: dict[str, str] = {}
    for skill_id in enabled_skills:
        skill_file = skills_root / skill_id / "SKILL.md"
        if skill_file.exists():
            loaded_skills[skill_id] = skill_file.read_text(encoding="utf-8")
    return loaded_skills


def serialize_trial_spec(
    task_dir: Path,
    instruction: str,
    config: ConfigSpec,
    model: ModelEntry,
) -> str:
    """Serialize the standardized `/io/spec.json` contract consumed by in-container runners."""
    spec_payload = {
        "task_id": task_dir.name,
        "instruction": instruction,
        "model_id": model.id,
        "litellm_model": model.litellm,
        "provider": model.provider,
        "api_base": model.api_base,
        "settings": config.settings.model_dump(mode="json"),
    }
    return json.dumps(spec_payload, indent=2)
