"""
@theora_tool — Decorator to mark a method as a THEORA agent tool.

Usage::

    class MyPlugin(TheoraPlugin):

        @theora_tool(
            name="search_web",
            description="Search the web for information",
            parameters={"query": {"type": "string", "description": "Search query"}}
        )
        async def search(self, query: str) -> dict:
            ...
"""

from __future__ import annotations
import inspect
from typing import Any, Callable


def theora_tool(
    name: str | None = None,
    description: str = "",
    parameters: dict[str, dict] | None = None,
) -> Callable:
    """Decorate an async method to register it as a THEORA tool.

    Args:
        name: Tool name (defaults to method name).
        description: Human-readable description shown to the LLM.
        parameters: Dict of param_name -> {type, description, required}.
            If omitted, inferred from type hints.
    """

    def decorator(fn: Callable) -> Callable:
        resolved_params = parameters
        if resolved_params is None:
            resolved_params = _infer_parameters(fn)

        fn._theora_tool_meta = {
            "name": name or fn.__name__,
            "description": description or fn.__doc__ or "",
            "parameters": resolved_params,
        }
        return fn

    return decorator


def _infer_parameters(fn: Callable) -> dict[str, dict[str, Any]]:
    """Infer tool parameters from function type hints."""
    sig = inspect.signature(fn)
    hints = getattr(fn, "__annotations__", {})
    params: dict[str, dict] = {}
    for pname, param in sig.parameters.items():
        if pname in ("self", "cls", "vault", "kwargs"):
            continue
        ptype = hints.get(pname, str)
        type_map = {str: "string", int: "integer", float: "number", bool: "boolean", list: "array", dict: "object"}
        params[pname] = {
            "type": type_map.get(ptype, "string"),
            "description": "",
            "required": param.default is inspect.Parameter.empty,
        }
    return params
