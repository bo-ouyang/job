"""Lazy public exports for Agent tools.

The default registry imports every concrete tool, so it must not be loaded
when callers only need a lightweight module such as ``agent.tools.base``.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .registry import AgentToolRegistry, agent_tool_registry, build_default_tool_registry


__all__ = [
    "AgentToolRegistry",
    "agent_tool_registry",
    "build_default_tool_registry",
]


def __getattr__(name: str):
    if name in __all__:
        from . import registry

        return getattr(registry, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
