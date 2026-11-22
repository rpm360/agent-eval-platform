"""Lint checks for the benchmark task suite and skill definitions."""

from __future__ import annotations

import os
from pathlib import Path

from eval_runner.schemas import TaskSpec

TASKS_DIR = Path("tasks")
SKILLS_DIR = Path("skills")


def test_task_suite_has_at_least_20_tasks_and_5_judge_tasks() -> None:
    task_dirs = [p for p in sorted(TASKS_DIR.iterdir()) if p.is_dir()]
    assert len(task_dirs) >= 20, f"Expected >= 20 tasks, got {len(task_dirs)}"
    judge_count = sum(1 for d in task_dirs if TaskSpec.from_dir(d).grader.type == "llm_judge")
    assert judge_count >= 5, f"Expected >= 5 llm_judge tasks, got {judge_count}"


def test_every_task_is_well_formed() -> None:
    for d in sorted(TASKS_DIR.iterdir()):
        if not d.is_dir():
            continue
        assert (d / "task.yaml").exists(), f"{d.name}: missing task.yaml"
        assert (d / "instruction.md").exists(), f"{d.name}: missing instruction.md"
        assert (d / "instruction.md").read_text(encoding="utf-8").strip(), f"{d.name}: empty instruction.md"

        spec = TaskSpec.from_dir(d)
        assert spec.id == d.name, f"{d.name}: task.yaml id {spec.id!r} != folder name"

        if spec.grader.type == "deterministic":
            script = d / spec.grader.script
            assert script.exists(), f"{d.name}: missing grader script {script}"
            assert os.access(script, os.X_OK), f"{d.name}: {script} is not executable"
        else:
            assert spec.grader.rubric and spec.grader.rubric.strip(), f"{d.name}: missing rubric"
            assert spec.grader.artifacts, f"{d.name}: judge task should declare artifacts"

        if "memory" in spec.discriminates or spec.category == "memory":
            has_seed = (d / "seed" / "MEMORY.md").exists() or (d / "seed_hermes" / "MEMORY.md").exists()
            assert has_seed, f"{d.name}: memory task missing seed/MEMORY.md"


def test_all_skills_have_skill_md() -> None:
    skill_dirs = [p for p in sorted(SKILLS_DIR.iterdir()) if p.is_dir()]
    assert len(skill_dirs) >= 3
    for sd in skill_dirs:
        assert (sd / "SKILL.md").exists(), f"{sd.name}: missing SKILL.md"
