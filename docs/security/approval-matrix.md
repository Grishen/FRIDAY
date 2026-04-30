# Approval Matrix & Blocked Actions

## Risk Levels

| Level | Description | Default approval |
|-------|-------------|------------------|
| LOW | Read-only, search, summarize | Automatic |
| MEDIUM | Drafts, create internal records | User confirmation (single tap) |
| HIGH | Sends email, modifies external state, sandboxed commands | Explicit approval |
| CRITICAL | Financial, legal, account ownership, physical access | Multi-step approval + cooldown |

## Tool Examples (initial catalog)

| Tool id | Risk | Requires approval |
|---------|------|-------------------|
| `calendar.read_events` | LOW | No |
| `calendar.create_event` | MEDIUM | Optional (configurable) |
| `email.create_draft` | MEDIUM | No |
| `email.send` | HIGH | Yes |
| `terminal.run_sandboxed` | HIGH | Yes |
| `smart_home.lock` | CRITICAL | Yes + re-auth |

## Blocked Actions (platform default)

Unless explicitly enabled by policy and user consent:

- Wire transfers or payment initiation.
- Legal filing or signature.
- Credential exfiltration or copying secrets to untrusted sinks.
- Disabling audit logging or tampering with audit tables.
- Arbitrary non-sandboxed host shell.

## Audit Requirements

Every tool invocation records: tool id, normalized inputs hash, outputs hash, risk level, approval id (if any), duration, outcome, correlation id.
