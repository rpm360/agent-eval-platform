"""Auto-discovered harness adapters package.

Drop a new `<harness>.py` module implementing and decorating a `HarnessAdapter`
with `@register_adapter` and it is discovered automatically without editing this file.
"""

from eval_runner.agents.base import (
    HarnessAdapter,
    discover_adapters,
    get_adapter,
    list_adapters,
    register_adapter,
)

discover_adapters()

__all__ = [
    "HarnessAdapter",
    "discover_adapters",
    "get_adapter",
    "list_adapters",
    "register_adapter",
]
