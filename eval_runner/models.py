"""ModelAdapter registry, LiteLLM Router configuration, retry handling, and token cost calculation."""

from __future__ import annotations

import importlib.metadata
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import yaml
import litellm
from litellm import Router
from litellm.exceptions import APIConnectionError, RateLimitError, ServiceUnavailableError, Timeout
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_random_exponential

from eval_runner.schemas import ModelCatalog, ModelEntry


class InfraModelError(RuntimeError):
    """Raised when an upstream LLM provider fails after all retries (must NOT be scored 0.0)."""


def load_models_catalog(path: Path = Path("models.yaml")) -> ModelCatalog:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return ModelCatalog.model_validate(data)


def get_api_keys_for_model(model: ModelEntry) -> list[str]:
    """Return primary (and optional secondary `_2`) API keys from the environment."""
    if not model.env_key:
        return []
    keys: list[str] = []
    primary = os.environ.get(model.env_key, "").strip()
    if primary:
        keys.append(primary)
    secondary = os.environ.get(f"{model.env_key}_2", "").strip()
    if secondary:
        keys.append(secondary)
    return keys


# Standard LiteLLM provider defaults when resolving raw `provider/model` strings without models.yaml
_PROVIDER_DEFAULTS: dict[str, tuple[str, str, list[str], bool, str | None]] = {
    # litellm_prefix: (normalized_provider, env_key, env_aliases, requires_api_key, default_api_base)
    "gemini": ("google", "GEMINI_API_KEY", ["GOOGLE_API_KEY"], True, None),
    "google": ("google", "GEMINI_API_KEY", ["GOOGLE_API_KEY"], True, None),
    "anthropic": ("anthropic", "ANTHROPIC_API_KEY", [], True, None),
    "openai": ("openai", "OPENAI_API_KEY", [], True, None),
    "openrouter": ("openrouter", "OPENROUTER_API_KEY", [], True, None),
    "groq": ("groq", "GROQ_API_KEY", [], True, None),
    "together_ai": ("together_ai", "TOGETHERAI_API_KEY", [], True, None),
    "together": ("together_ai", "TOGETHERAI_API_KEY", [], True, None),
    "mistral": ("mistral", "MISTRAL_API_KEY", [], True, None),
    "deepseek": ("deepseek", "DEEPSEEK_API_KEY", [], True, None),
    "ollama": ("ollama", "", [], False, "http://host.docker.internal:11434"),
    "ollama_chat": ("ollama", "", [], False, "http://host.docker.internal:11434"),
    "mock": ("mock", "", [], False, None),
}


def resolve_model(catalog: ModelCatalog, model_ref: str) -> ModelEntry:
    """Resolve a model by catalog ID (models.yaml) OR directly as a LiteLLM `provider/model` string."""
    try:
        return catalog.get(model_ref)
    except KeyError:
        pass

    if "/" not in model_ref:
        raise KeyError(
            f"Unknown model '{model_ref}'. Use an id from models.yaml "
            f"({[m.id for m in catalog.models]}) or a LiteLLM 'provider/model' string "
            f"(e.g. 'gemini/gemini-2.5-flash', 'openrouter/qwen/qwen-2.5-coder-32b-instruct')."
        )

    prefix = model_ref.split("/", 1)[0].lower()
    if prefix in _PROVIDER_DEFAULTS:
        provider, env_key, aliases, req_key, api_base = _PROVIDER_DEFAULTS[prefix]
    else:
        provider = prefix
        env_key = f"{prefix.upper()}_API_KEY"
        aliases = []
        req_key = True
        api_base = None

    return ModelEntry(
        id=model_ref,
        litellm=model_ref,
        provider=provider,
        adapter="mock" if provider == "mock" else "litellm",
        env_key=env_key,
        env_aliases=list(aliases),
        api_base=api_base,
        requires_api_key=req_key,
    )


def estimate_cost_usd(model: ModelEntry, input_tokens: int, output_tokens: int) -> float:
    if model.pricing.input_per_mtok > 0 or model.pricing.output_per_mtok > 0:
        in_cost = (input_tokens / 1_000_000.0) * model.pricing.input_per_mtok
        out_cost = (output_tokens / 1_000_000.0) * model.pricing.output_per_mtok
        return round(in_cost + out_cost, 6)
    if model.provider != "mock" and (input_tokens > 0 or output_tokens > 0):
        try:
            in_cost, out_cost = litellm.cost_per_token(
                model=model.litellm,
                prompt_tokens=input_tokens,
                completion_tokens=output_tokens,
            )
            return round(float(in_cost) + float(out_cost), 6)
        except Exception:
            pass
    return 0.0


_RETRYABLE_EXCEPTIONS = (
    RateLimitError,
    APIConnectionError,
    ServiceUnavailableError,
    Timeout,
    ConnectionError,
    TimeoutError,
)


@retry(
    wait=wait_random_exponential(min=1, max=30),
    stop=stop_after_attempt(4),
    retry=retry_if_exception_type(_RETRYABLE_EXCEPTIONS),
    reraise=True,
)
def _call_router(router: Router, model_id: str, messages: list[dict[str, Any]], **kwargs: Any) -> Any:
    return router.completion(model=model_id, messages=messages, **kwargs)


def build_litellm_router(model: ModelEntry) -> Router:
    """Build a LiteLLM Router with automatic 429 retries, key rotation, and optional fallback."""
    keys = get_api_keys_for_model(model)
    if model.requires_api_key and model.provider != "mock" and not keys:
        raise InfraModelError(
            f"Missing API key environment variable '{model.env_key}' for model '{model.id}'."
        )

    model_list: list[dict[str, Any]] = []
    if keys:
        for key in keys:
            params: dict[str, Any] = {"model": model.litellm, "api_key": key}
            if model.api_base:
                params["api_base"] = model.api_base
            model_list.append({"model_name": model.id, "litellm_params": params})
    else:
        params = {"model": model.litellm}
        if model.api_base:
            params["api_base"] = model.api_base
        model_list.append({"model_name": model.id, "litellm_params": params})

    fallbacks: list[dict[str, list[str]]] = []
    if model.fallback:
        fallback_name = f"{model.id}-fallback"
        fb_params: dict[str, Any] = {"model": model.fallback}
        if keys:
            fb_params["api_key"] = keys[0]
        if model.api_base:
            fb_params["api_base"] = model.api_base
        model_list.append({"model_name": fallback_name, "litellm_params": fb_params})
        fallbacks.append({model.id: [fallback_name]})

    return Router(
        model_list=model_list,
        fallbacks=fallbacks,
        num_retries=4,
        retry_after=5,
        allowed_fails=2,
        cooldown_time=30,
    )


class ModelAdapter(ABC):
    """Common interface for model providers (LiteLLM, mock, or custom gateway adapters)."""

    name: str

    @abstractmethod
    def build_container_env(self, model: ModelEntry) -> dict[str, str]:
        """Return provider/auth environment variables to pass into an agent container."""

    @abstractmethod
    def complete(
        self,
        model: ModelEntry,
        messages: list[dict[str, Any]],
        temperature: float = 0.0,
        **kwargs: Any,
    ) -> tuple[str, int, int]:
        """Execute a chat completion and return (content, input_tokens, output_tokens)."""


_MODEL_ADAPTERS: dict[str, type[ModelAdapter]] = {}
_MODEL_EPS_LOADED = False


def register_model_adapter(cls: type[ModelAdapter]) -> type[ModelAdapter]:
    _MODEL_ADAPTERS[cls.name] = cls
    return cls


def _load_model_entry_points() -> None:
    global _MODEL_EPS_LOADED
    if _MODEL_EPS_LOADED:
        return
    _MODEL_EPS_LOADED = True
    try:
        eps = importlib.metadata.entry_points(group="agent_eval.models")
    except Exception:
        return
    for ep in eps:
        try:
            ep.load()
        except Exception:
            continue


def get_model_adapter(name: str) -> ModelAdapter:
    _load_model_entry_points()
    if name not in _MODEL_ADAPTERS:
        raise KeyError(
            f"Unknown model adapter '{name}'. Registered: {sorted(_MODEL_ADAPTERS.keys())}"
        )
    return _MODEL_ADAPTERS[name]()


def list_model_adapters() -> list[str]:
    _load_model_entry_points()
    return sorted(_MODEL_ADAPTERS.keys())


@register_model_adapter
class LiteLLMModelAdapter(ModelAdapter):
    """Unified adapter for Google, Anthropic, OpenAI, OpenRouter, Ollama, vLLM via LiteLLM."""

    name = "litellm"

    def build_container_env(self, model: ModelEntry) -> dict[str, str]:
        env: dict[str, str] = {}
        if model.api_base:
            env["LITELLM_API_BASE"] = model.api_base
        if not model.requires_api_key or model.provider == "mock":
            return env
        keys = get_api_keys_for_model(model)
        if not keys:
            raise InfraModelError(
                f"Missing API key '{model.env_key}' in environment/.env for model '{model.id}'."
            )
        if model.env_key:
            env[model.env_key] = keys[0]
        for alias in model.env_aliases:
            env[alias] = keys[0]
        return env

    def complete(
        self,
        model: ModelEntry,
        messages: list[dict[str, Any]],
        temperature: float = 0.0,
        **kwargs: Any,
    ) -> tuple[str, int, int]:
        router = build_litellm_router(model)
        try:
            resp = _call_router(router, model.id, messages, temperature=temperature, **kwargs)
        except Exception as exc:
            raise InfraModelError(f"Model call failed after retries ({model.id}): {exc}") from exc

        content = resp.choices[0].message.content or ""
        usage = getattr(resp, "usage", None)
        in_tok = int(getattr(usage, "prompt_tokens", 0) or 0)
        out_tok = int(getattr(usage, "completion_tokens", 0) or 0)
        return content, in_tok, out_tok


@register_model_adapter
class MockModelAdapter(ModelAdapter):
    """Deterministic zero-key adapter for smoke tests."""

    name = "mock"

    def build_container_env(self, model: ModelEntry) -> dict[str, str]:
        return {}

    def complete(
        self,
        model: ModelEntry,
        messages: list[dict[str, Any]],
        temperature: float = 0.0,
        **kwargs: Any,
    ) -> tuple[str, int, int]:
        return '{"score": 1.0, "passed": true, "reasoning": "Mock model response."}', 0, 0


def call_model_with_retry(
    model: ModelEntry,
    messages: list[dict[str, Any]],
    temperature: float = 0.0,
    **kwargs: Any,
) -> tuple[str, int, int]:
    """Call any configured model via its registered ModelAdapter. Returns (content, in_tok, out_tok)."""
    adapter = get_model_adapter(model.adapter)
    return adapter.complete(model, messages, temperature=temperature, **kwargs)
