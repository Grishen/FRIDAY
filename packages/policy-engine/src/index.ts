export type RiskTier = "low" | "medium" | "high" | "critical";

export function requiresApproval(tier: RiskTier): boolean {
  return tier === "high" || tier === "critical";
}

export function describeRisk(tier: RiskTier): string {
  const map: Record<RiskTier, string> = {
    low: "safe read-only",
    medium: "drafts or internal writes",
    high: "external side effects",
    critical: "irreversible or regulated",
  };
  return map[tier];
}
