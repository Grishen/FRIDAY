# FRIDAY Personal AI Operating System — Product Vision

## North Star

FRIDAY is not a chatbot. It is a **personal AI operating layer** that perceives multimodal input (voice, text, files, screen context), reasons with durable memory, acts through a **tool gateway** with policy and approvals, and delivers responses through voice and UI—with full **auditability** and **security** from day one.

## Personas

1. **Individual professional** — Wants Jarvis-grade briefings, meeting prep, task tracking, and document intelligence without babysitting prompts.
2. **Software engineer** — Needs repo-aware assistance, sandboxed execution, PR summaries, and safe patch proposals behind approval gates.
3. **Operator / power user** — Demands deterministic workflows (daily briefing, meeting prep), pause/resume, and integration with calendars, email, and GitHub.
4. **Security-conscious user** — Requires transparent risk scoring, explicit approvals for high-risk tools, and immutable audit trails.

## Capability Matrix (v1 → v3)

| Capability | v1 (Weeks 1–4) | v2 | v3 |
|------------|----------------|----|----|
| Multimodal chat + WebSocket | ✓ | Streaming upgrades | Full realtime multimodal |
| Voice UI + status UX | Skeleton | Streaming STT/TTS | Wake word |
| Memory (4 types) + pgvector | Core + APIs | Conflict resolution | Cross-device sync |
| Tool gateway + policy | ✓ mocks | Real integrations | Expanded catalog |
| RAG + citations | Chunk + search | Hybrid + rerank | Email/web ingest |
| Workflows | State machine | Temporal/Celery | Cross-service orchestration |
| Desktop / screen | Architecture only | Context APIs | Tauri shell |
| Proactive / notifications | Audit + in-app | Rules engine | Smart quiet hours |

## Success Criteria (First Demo)

**Prompt:** “Friday, prepare me for tomorrow.”

**Expected behavior:** Calendar scan → meetings → tasks → related email summaries (mock/read) → document search → prioritized summary → optional drafts/reminders with **approval** for outbound actions.

## Non-Goals (v1)

- Fully autonomous unattended financial or legal submissions.
- Unrestricted shell on host machine (sandboxed stubs only until hardened).
- Replacing OAuth providers’ own consent UX.

## Principles

1. **No toy logic in route handlers** — Orchestration belongs in agents and services.
2. **Providers are swappable** — LLM, embedding, vision, rerank behind interfaces.
3. **Tools never bypass the gateway** — Registry, validation, risk, approval, audit.
4. **Every sensitive path is observable** — Structured logs + audit events + trace IDs (OTel-ready).
