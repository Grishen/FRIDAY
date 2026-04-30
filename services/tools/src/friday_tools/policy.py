"""Policy engine — risk scoring and approval requirements."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from friday_tools.registry import RegisteredTool
from friday_tools.types import RiskLevel


class PolicyDecision(BaseModel):
    allowed: bool
    requires_approval: bool
    effective_risk: RiskLevel
    reasons: list[str] = Field(default_factory=list)


class PolicyEngine:
    """Configurable ruleset; starts conservative."""

    def evaluate(self, tool: RegisteredTool, user_id: UUID) -> PolicyDecision:  # noqa: ARG002
        reasons: list[str] = []
        requires = tool.requires_approval or tool.risk_level in (
            RiskLevel.HIGH,
            RiskLevel.CRITICAL,
        )
        allowed = tool.risk_level != RiskLevel.CRITICAL or requires
        if tool.risk_level == RiskLevel.CRITICAL:
            reasons.append("critical_risk_requires_explicit_approval_flow")
        return PolicyDecision(
            allowed=allowed,
            requires_approval=requires,
            effective_risk=tool.risk_level,
            reasons=reasons,
        )
