export type RiskTier = "low" | "medium" | "high" | "critical";

export type IntentLabel =
  | "question"
  | "task"
  | "reminder"
  | "research"
  | "coding"
  | "calendar"
  | "email"
  | "meeting_prep"
  | "document_search"
  | "system_command"
  | "smart_home"
  | "unknown";

export type AssistantEnvelope = {
  traceId: string;
  intent: IntentLabel;
  tools: Array<{ tool: string; status: string; envelope: unknown }>;
};
