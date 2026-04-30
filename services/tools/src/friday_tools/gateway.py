"""Single execution path for tools — validate, policy, approve gate, run, normalize."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import jsonschema

from friday_tools.policy import PolicyEngine
from friday_tools.registry import ToolRegistry
from friday_tools.types import ToolInvocation, ToolResult


class ToolGateway:
    def __init__(self, registry: ToolRegistry, policy: PolicyEngine) -> None:
        self._registry = registry
        self._policy = policy

    @staticmethod
    def _handler_kwargs(inv: ToolInvocation) -> dict[str, Any]:
        """Merge tool input with execution context (validated input only appears in ``inv.input``)."""

        out: dict[str, Any] = {**dict(inv.input), "user_id": inv.user_id}
        if inv.session_id is not None:
            out["session_id"] = inv.session_id
        if inv.trace_id is not None:
            out["trace_id"] = inv.trace_id
        return out

    @property
    def registry(self) -> ToolRegistry:
        return self._registry

    def _validate_input(self, schema: dict[str, Any], data: dict[str, Any]) -> None:
        if not schema:
            return
        jsonschema.validate(instance=data, schema=schema)

    async def propose(
        self,
        inv: ToolInvocation,
    ) -> tuple[str, dict[str, Any]]:
        """Validate + policy; returns (status, envelope) where status is proceed|pending_approval."""
        tool = self._registry.get(inv.tool_name)
        if not tool:
            return "error", {"error": f"unknown_tool:{inv.tool_name}"}
        handler = self._registry.handler(inv.tool_name)
        if not handler:
            return "error", {"error": f"no_handler:{inv.tool_name}"}
        self._validate_input(dict(tool.input_schema), dict(inv.input))
        decision = self._policy.evaluate(tool, inv.user_id)
        if not decision.allowed:
            return "blocked", {"reasons": decision.reasons}
        if decision.requires_approval:
            approval_id = str(uuid4())
            return "pending_approval", {"approval_id": approval_id, "decision": decision.model_dump()}
        result = await self.execute_approved(inv)
        return "completed", result.model_dump()

    async def execute_approved(self, inv: ToolInvocation) -> ToolResult:
        tool = self._registry.get(inv.tool_name)
        if not tool:
            return ToolResult(ok=False, error=f"unknown_tool:{inv.tool_name}")
        handler = self._registry.handler(inv.tool_name)
        if not handler:
            return ToolResult(ok=False, error=f"no_handler:{inv.tool_name}")
        self._validate_input(dict(tool.input_schema), dict(inv.input))
        try:
            raw = await handler(**self._handler_kwargs(inv))
            out: dict[str, Any] = dict(raw) if isinstance(raw, dict) else {"result": raw}
            self._validate_output(dict(tool.output_schema), out)
            return ToolResult(ok=True, output=out)
        except Exception as e:  # noqa: BLE001
            return ToolResult(ok=False, error=str(e))

    def _validate_output(self, schema: dict[str, Any], data: dict[str, Any]) -> None:
        if not schema:
            return
        jsonschema.validate(instance=data, schema=schema)
