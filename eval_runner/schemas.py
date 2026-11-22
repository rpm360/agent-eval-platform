"""Pydantic schemas and deterministic config hashing for the evaluation runner."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field


class ModelPricing(BaseModel):
    input_per_mtok: float = 0.0
    output_per_mtok: float = 0.0


class ModelEntry(BaseModel):
    id: str
    litellm: str
    provider: str
    adapter: str = "litellm"
    env_key: str = ""
    env_aliases: list[str] = Field(default_factory=list)
    api_base: str | None = None
    requires_api_key: bool = True
    fallback: str | None = None
    pricing: ModelPricing = Field(default_factory=ModelPricing)


class ModelCatalog(BaseModel):
    models: list[ModelEntry]

    def get(self, model_id: str) -> ModelEntry:
        for m in self.models:
            if m.id == model_id:
                return m
        raise KeyError(f"Unknown model id '{model_id}'. Available: {[m.id for m in self.models]}")


class Settings(BaseModel):
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_steps: int = Field(default=20, gt=0)
    timeout_sec: int = Field(default=180, gt=0)
    memory: bool = False
    skills: list[str] = Field(default_factory=list)
    system_prompt_append: str | None = None
    tools: list[str] | None = None
    max_output_tokens: int | None = Field(default=None, gt=0)
    max_total_tokens: int | None = Field(default=None, gt=0)


class ConfigSpec(BaseModel):
    name: str
    harness: str  # registered HarnessAdapter name
    model: str  # catalog id from models.yaml
    settings: Settings = Field(default_factory=Settings)

    @classmethod
    def from_yaml(cls, path: Path) -> ConfigSpec:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return cls.model_validate(data)


def compute_config_hash(config: ConfigSpec, model_entry: ModelEntry) -> str:
    """Deterministic SHA-256 hash of a config version.

    Excludes `pricing` so provider price changes do not mint a new config version.
    Omits optional `tools`, `max_output_tokens`, `max_total_tokens`, and `api_base` when None
    so existing hashes remain backward-compatible.
    """
    settings_dict = config.settings.model_dump(mode="json")
    for opt_key in ("tools", "max_output_tokens", "max_total_tokens"):
        if settings_dict.get(opt_key) is None:
            settings_dict.pop(opt_key, None)

    canonical_payload: dict[str, Any] = {
        "name": config.name,
        "harness": config.harness,
        "model_id": model_entry.id,
        "litellm": model_entry.litellm,
        "provider": model_entry.provider,
        "settings": settings_dict,
    }
    if model_entry.api_base is not None:
        canonical_payload["api_base"] = model_entry.api_base
    blob = json.dumps(canonical_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:12]


class GraderSpec(BaseModel):
    type: Literal["deterministic", "llm_judge"] = "deterministic"
    script: str = "tests/test.sh"
    rubric: str | None = None
    judge_model: str | None = None
    pass_threshold: float = 0.7
    artifacts: list[str] = Field(default_factory=list)


class TaskSpec(BaseModel):
    id: str
    category: str = "general"
    description: str = ""
    discriminates: list[str] = Field(default_factory=list)
    timeout_sec: int = 180
    grader: GraderSpec = Field(default_factory=GraderSpec)

    @classmethod
    def from_dir(cls, task_dir: Path) -> TaskSpec:
        meta_path = task_dir / "task.yaml"
        if meta_path.exists():
            data = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}
            data.setdefault("id", task_dir.name)
            return cls.model_validate(data)
        return cls(id=task_dir.name)


class TraceEvent(BaseModel):
    seq: int
    ts: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    type: Literal[
        "session_start",
        "message",
        "tool_call",
        "tool_result",
        "memory_op",
        "skill_invoked",
        "model_call",
        "error",
        "session_end",
    ]
    payload: dict[str, Any] = Field(default_factory=dict)


class GradeResult(BaseModel):
    grader_type: str
    score: float
    passed: bool
    reasoning: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


class TrialResult(BaseModel):
    trial_id: str
    experiment_id: str
    config_name: str
    config_hash: str
    harness: str
    model: str
    task_id: str
    trial_index: int
    status: Literal["completed", "infra_error"]
    score: float | None = None
    passed: bool | None = None
    runtime_sec: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    steps: int = 0
    final_answer: str = ""
    grade: GradeResult | None = None
    failure_category: str | None = None
    error_message: str | None = None
    trace_path: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
