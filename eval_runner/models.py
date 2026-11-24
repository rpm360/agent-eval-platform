"""ModelAdapter registry, LiteLLM Router configuration, retry handling, and token cost calculation."""

from __future__ import annotations

import importlib.metadata
import logging
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import litellm
import yaml
from litellm import Router

litellm.drop_params = True

from litellm.exceptions import (  # noqa: E402
    APIConnectionError,
    RateLimitError,
    ServiceUnavailableError,
    Timeout,
)
from tenacity import (  # noqa: E402
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from eval_runner.constants import TOKENS_PER_MILLION  # noqa: E402
from eval_runner.schemas import ModelCatalog, ModelEntry  # noqa: E402

logger = logging.getLogger(__name__)

MODEL_ENTRY_POINT_GROUP = "agent_eval.models"
DEFAULT_OLLAMA_DOCKER_BASE = "http://host.docker.internal:11434"
RETRY_MIN_WAIT_SEC = 1
RETRY_MAX_WAIT_SEC = 30
MAX_COMPLETION_ATTEMPTS = 4
ROUTER_RETRY_AFTER_SEC = 5
ROUTER_ALLOWED_FAILS = 2
ROUTER_COOLDOWN_SEC = 30
COST_DECIMAL_PLACES = 6
MOCK_JUDGE_RESPONSE_JSON = '{"score": 1.0, "passed": true, "reasoning": "Mock model response."}'


class InfraModelError(RuntimeError):
    """Raised when an upstream LLM provider fails after all retries (must NOT be scored 0.0)."""


def load_models_catalog(path: Path = Path("models.yaml")) -> ModelCatalog:
    """Load and validate `models.yaml` into a `ModelCatalog`."""
    catalog_data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return ModelCatalog.model_validate(catalog_data)


def get_api_keys_for_model(model: ModelEntry) -> list[str]:
    """Return primary (and optional secondary `_2`) API keys from the environment."""
    if not model.env_key:
        return []
    api_keys: list[str] = []
    primary_key = os.environ.get(model.env_key, "").strip()
    if primary_key:
        api_keys.append(primary_key)
    secondary_key = os.environ.get(f"{model.env_key}_2", "").strip()
    if secondary_key:
        api_keys.append(secondary_key)
    return api_keys


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
    "ollama": ("ollama", "", [], False, DEFAULT_OLLAMA_DOCKER_BASE),
    "ollama_chat": ("ollama", "", [], False, DEFAULT_OLLAMA_DOCKER_BASE),
    "mock": ("mock", "", [], False, None),
}


def resolve_model(catalog: ModelCatalog, model_ref: str) -> ModelEntry:
    """Resolve a model by catalog ID (`models.yaml`) OR directly as a LiteLLM `provider/model` string."""
    try:
        return catalog.get(model_ref)
    except KeyError:
        pass

    if "/" not in model_ref:
        available_ids = [entry.id for entry in catalog.models]
        raise KeyError(
            f"Unknown model '{model_ref}'. Use an id from models.yaml "
            f"({available_ids}) or a LiteLLM 'provider/model' string "
            f"(e.g. 'gemini/gemini-2.5-flash', 'openrouter/qwen/qwen-2.5-coder-32b-instruct')."
        )

    prefix = model_ref.split("/", 1)[0].lower()
    if prefix in _PROVIDER_DEFAULTS:
        provider, env_key, env_aliases, requires_key, api_base = _PROVIDER_DEFAULTS[prefix]
    else:
        provider = prefix
        env_key = f"{prefix.upper()}_API_KEY"
        env_aliases = []
        requires_key = True
        api_base = None

    return ModelEntry(
        id=model_ref,
        litellm=model_ref,
        provider=provider,
        adapter="mock" if provider == "mock" else "litellm",
        env_key=env_key,
        env_aliases=list(env_aliases),
        api_base=api_base,
        requires_api_key=requires_key,
    )


def estimate_cost_usd(model: ModelEntry, input_tokens: int, output_tokens: int) -> float:
    """Compute trial USD spend from `models.yaml` rates, falling back to LiteLLM's pricing table."""
    if model.pricing.input_per_mtok > 0 or model.pricing.output_per_mtok > 0:
        input_cost = (input_tokens / TOKENS_PER_MILLION) * model.pricing.input_per_mtok
        output_cost = (output_tokens / TOKENS_PER_MILLION) * model.pricing.output_per_mtok
        return round(input_cost + output_cost, COST_DECIMAL_PLACES)

    if model.provider != "mock" and (input_tokens > 0 or output_tokens > 0):
        try:
            input_cost, output_cost = litellm.cost_per_token(
                model=model.litellm,
                prompt_tokens=input_tokens,
                completion_tokens=output_tokens,
            )
            return round(float(input_cost) + float(output_cost), COST_DECIMAL_PLACES)
        except Exception as exc:
            logger.debug("LiteLLM cost fallback unavailable for %s: %s", model.litellm, exc)
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
    wait=wait_random_exponential(min=RETRY_MIN_WAIT_SEC, max=RETRY_MAX_WAIT_SEC),
    stop=stop_after_attempt(MAX_COMPLETION_ATTEMPTS),
    retry=retry_if_exception_type(_RETRYABLE_EXCEPTIONS),
    reraise=True,
)
def _call_router(
    router: Router, model_id: str, messages: list[dict[str, Any]], **kwargs: Any
) -> Any:
    return router.completion(model=model_id, messages=messages, **kwargs)


def build_litellm_router(model: ModelEntry) -> Router:
    """Build a LiteLLM Router with automatic 429 retries, key rotation, and optional fallback."""
    api_keys = get_api_keys_for_model(model)
    if model.requires_api_key and model.provider != "mock" and not api_keys:
        raise InfraModelError(
            f"Missing API key environment variable '{model.env_key}' for model '{model.id}'."
        )

    deployments: list[dict[str, Any]] = []
    if api_keys:
        for api_key in api_keys:
            litellm_params: dict[str, Any] = {"model": model.litellm, "api_key": api_key}
            if model.api_base:
                litellm_params["api_base"] = model.api_base
            deployments.append({"model_name": model.id, "litellm_params": litellm_params})
    else:
        litellm_params = {"model": model.litellm}
        if model.api_base:
            litellm_params["api_base"] = model.api_base
            if not model.requires_api_key:
                litellm_params["api_key"] = "unauthenticated"
        deployments.append({"model_name": model.id, "litellm_params": litellm_params})

    fallbacks: list[dict[str, list[str]]] = []
    if model.fallback:
        fallback_name = f"{model.id}-fallback"
        fallback_params: dict[str, Any] = {"model": model.fallback}
        if api_keys:
            fallback_params["api_key"] = api_keys[0]
        if model.api_base:
            fallback_params["api_base"] = model.api_base
        deployments.append({"model_name": fallback_name, "litellm_params": fallback_params})
        fallbacks.append({model.id: [fallback_name]})

    return Router(
        model_list=deployments,
        fallbacks=fallbacks,
        num_retries=MAX_COMPLETION_ATTEMPTS,
        retry_after=ROUTER_RETRY_AFTER_SEC,
        allowed_fails=ROUTER_ALLOWED_FAILS,
        cooldown_time=ROUTER_COOLDOWN_SEC,
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
        """Execute a chat completion and return `(content, input_tokens, output_tokens)`."""


_MODEL_ADAPTERS: dict[str, type[ModelAdapter]] = {}
_MODEL_EPS_LOADED = False


def register_model_adapter(cls: type[ModelAdapter]) -> type[ModelAdapter]:
    """Class decorator registering a `ModelAdapter` implementation by its `name`."""
    _MODEL_ADAPTERS[cls.name] = cls
    return cls


def _load_model_entry_points() -> None:
    global _MODEL_EPS_LOADED
    if _MODEL_EPS_LOADED:
        return
    _MODEL_EPS_LOADED = True
    try:
        entry_points = importlib.metadata.entry_points(group=MODEL_ENTRY_POINT_GROUP)
    except Exception as exc:
        logger.debug("Could not query %s entry points: %s", MODEL_ENTRY_POINT_GROUP, exc)
        return
    for entry_point in entry_points:
        try:
            entry_point.load()
        except Exception as exc:
            logger.warning("Failed to load model entry point '%s': %s", entry_point.name, exc)


def get_model_adapter(name: str) -> ModelAdapter:
    """Instantiate a registered `ModelAdapter` by name."""
    _load_model_entry_points()
    if name not in _MODEL_ADAPTERS:
        raise KeyError(
            f"Unknown model adapter '{name}'. Registered: {sorted(_MODEL_ADAPTERS.keys())}"
        )
    return _MODEL_ADAPTERS[name]()


def list_model_adapters() -> list[str]:
    """Return sorted names of all registered `ModelAdapter` implementations."""
    _load_model_entry_points()
    return sorted(_MODEL_ADAPTERS.keys())


@register_model_adapter
class LiteLLMModelAdapter(ModelAdapter):
    """Unified adapter for Google, Anthropic, OpenAI, OpenRouter, Ollama, and vLLM via LiteLLM."""

    name = "litellm"

    def build_container_env(self, model: ModelEntry) -> dict[str, str]:
        container_env: dict[str, str] = {}
        if model.api_base:
            container_env["LITELLM_API_BASE"] = model.api_base
        if not model.requires_api_key or model.provider == "mock":
            if model.api_base and model.litellm.startswith("openai/"):
                container_env["OPENAI_API_KEY"] = "unauthenticated"
            return container_env

        api_keys = get_api_keys_for_model(model)
        if not api_keys:
            raise InfraModelError(
                f"Missing API key '{model.env_key}' in environment/.env for model '{model.id}'."
            )
        if model.env_key:
            container_env[model.env_key] = api_keys[0]
        for alias in model.env_aliases:
            container_env[alias] = api_keys[0]
        return container_env

    def complete(
        self,
        model: ModelEntry,
        messages: list[dict[str, Any]],
        temperature: float = 0.0,
        **kwargs: Any,
    ) -> tuple[str, int, int]:
        router = build_litellm_router(model)
        try:
            completion_response = _call_router(
                router, model.id, messages, temperature=temperature, **kwargs
            )
        except Exception as exc:
            raise InfraModelError(f"Model call failed after retries ({model.id}): {exc}") from exc

        content = completion_response.choices[0].message.content or ""
        usage = getattr(completion_response, "usage", None)
        input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        return content, input_tokens, output_tokens


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
        return MOCK_JUDGE_RESPONSE_JSON, 0, 0


def call_model_with_retry(
    model: ModelEntry,
    messages: list[dict[str, Any]],
    temperature: float = 0.0,
    **kwargs: Any,
) -> tuple[str, int, int]:
    """Call any configured model via its registered `ModelAdapter`."""
    adapter = get_model_adapter(model.adapter)
    return adapter.complete(model, messages, temperature=temperature, **kwargs)
