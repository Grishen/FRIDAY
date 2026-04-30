"""Process-level singletons wired during application startup."""

from __future__ import annotations

from friday_tools import ToolGateway


_gateway: ToolGateway | None = None


def configure_gateway(gateway: ToolGateway) -> None:
    global _gateway  # noqa: PLW0603 - intentional singleton cache
    _gateway = gateway


def get_tool_gateway() -> ToolGateway:
    if _gateway is None:
        raise RuntimeError("Tool gateway not configured")
    return _gateway
