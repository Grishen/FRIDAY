# REST API (v1) — Contract Sketch

Base URL: `/api/v1`

*(Root app also serves machine-readable **`GET /openapi.json`**, Swagger **`/docs`**, and ReDoc **`/redoc`**. A checked-in snapshot lives at **`docs/api/openapi.json`** — regenerate with **`PYTHONPATH=services/api/src python scripts/export-openapi.py`**.)*

## Developer platform (Phase 9)

Public — no `X-User-Id`:

- **`GET /meta`** — Service name, package version (`importlib.metadata`), `environment`, optional `build_id` from `FRIDAY_BUILD_ID` / `GIT_COMMIT_SHA`, `{ openapi_json, swagger_ui, redoc }` paths, and **`observability`** (Phase 13): tracing on/off, exporter family, `service_name`, sanitized OTLP host/scheme (no secrets).
- **`GET /ready`** — `{ status, database, redis, *_error }`. Returns **`503`** if Postgres is unreachable; **`200`** with `degraded` if only Redis fails.

## Auth

- `POST /auth/register` — Local dev user (optional in production).
- `POST /auth/token` — OAuth2 password flow (dev) or exchange.
- `GET /auth/providers` — List configured OAuth providers.

*(Full OAuth redirect flows added in Auth service hardening phase.)*

## Sessions & Chat

- `POST /sessions` — Create session `{ title?: string }` → `{ id, user_id, created_at }`.
- `GET /sessions` — List sessions for current user.
- `GET /sessions/{id}/messages` — Paginated messages.
- `POST /sessions/{id}/messages` — Post user message; server runs orchestration (sync response). Assistant **`meta`** includes **`intent`**, structured **`plan`** (`PlanSpec`), **`context_summary`** (transcript/memory counts + tool catalog), and per-tool **`tools`** results — same envelope on WebSocket `assistant.message`.
- **`POST /sessions/{id}/messages/stream`** — Same turn as `/messages`, but **`text/event-stream`** (SSE). Typical events:
  - `conversation.user` — persisted user row id + echoed text.
  - `assistant.delta` — incremental LLM text (tokens / coarse chunks depending on provider).
  - `assistant.message` — final assistant **`id`**, **`content`**, **`meta`** (same envelope as REST sync).
  - `error` — unhandled turn failure (**`detail`** string).
  - `done` — stream complete ( `{}` ).
- **`POST /sessions/{id}/transcribe`** — **`multipart/form-data`** field **`file`** (≤ `STT_MAX_UPLOAD_BYTES`). Uses **`OPENAI_API_KEY`** against **`OPENAI_BASE_URL`/audio/transcriptions** with **`OPENAI_WHISPER_MODEL`** (default `whisper-1`). When **`FRIDAY_PYTEST=1`** and no API key, returns deterministic mock text without calling the cloud.
- **`POST /sessions/{id}/realtime/webrtc`** — SDP offer body (`Content-Type: application/sdp`). Authenticated **`X-User-Id`**. Forwards multipart (`sdp`,`session`) to OpenAI **`POST /v1/realtime/calls`** (see OpenAI unified WebRTC Realtime docs) and returns **answer SDP** as `application/sdp`. **`OPENAI_API_KEY`** plus **`OPENAI_REALTIME_*`**/`FRIDAY_REALTIME_INSTRUCTIONS` configure upstream. **Bypasses orchestration/tool policies** today — use text/WebSocket + planner until Realtime MCP / server intercept is wired.

## Memory

Auth header `X-User-Id` (development).

- `GET /memory` — Query params: `memory_type` (optional), `limit` (1–500). Response `{ items: [...] }` (`MemoryOut` each).
- `POST /memory` — Body: `memory_type` (`profile` | `episodic` | `semantic` | `task`), `content`, optional `importance_score`, optional `embedding`/`metadata`, `sensitivity_level`. Embedding generated server-side via mock adapter if omitted.
- `PATCH /memory/{id}` — Partial update (`MemoryUpdate`).
- `DELETE /memory/{id}` — Returns `204` on success.
- `POST /memory/search` — Body: `{ "query": string, "memory_type"?: string, "limit"?: number }` → `{ "hits": [ { "memory": MemoryOut, "score": number } ] }`. Ranking uses **PostgreSQL pgvector** cosine distance in SQL (`embedding <=> query_vector`); `score` maps that distance to ~`[0,1]` for consistent UI.

## Tools & Approvals

- `GET /tools` — Registered tools (metadata only; from in-process `ToolRegistry` + `PolicyEngine` at startup).
- `GET /approvals?approval_status=pending` — List approvals; each item includes **`tool_name`** (from joined `ToolCall`) when present.
- `POST /approvals/{approval_id}/resolve` — Body `{ "decision": "approve" | "deny", "reason"?: string }`. Writes **`approval.approved` / `approval.denied`** audit events. On **approve**, marks `ToolCall` **`queued`**, enqueues Celery `friday.tasks.execute_tool_call`. Worker completion adds **`tool.execution_completed` / `tool.execution_failed`** audit rows.

When a tool invocation returns `pending_approval` from `ToolGateway`, the API stores a `ToolCall` (`awaiting_approval`) and an `Approval` row keyed by the gateway’s `approval_id`.

## Audit

Auth header `X-User-Id` (development).

- `GET /audit?limit=50` — Recent `AuditLog` rows for the current user (default limit 50, max 200).

Policy **blocks** emit `tool.policy_blocked` during orchestration when the gateway returns `blocked`.

## Workflows

Auth header `X-User-Id` (development).

- `GET /workflows/templates` — Template catalog (`daily_briefing`, `meeting_prep`) with titles and step counts.
- `GET /workflows` — List current user’s workflow instances (includes step rows).
- `POST /workflows` — Body `{ "template": "daily_briefing" | "meeting_prep" }` — create instance, run immediate steps, stop at first tool step (usually `waiting_for_approval` + pending approval if policy requires it).
- `GET /workflows/{id}` — Single workflow + steps.
- `POST /workflows/{id}/advance` — Run the current step (immediate or tool proposal).
- `POST /workflows/{id}/pause` | `/resume` | `/cancel` — State machine control.

Tool calls created from workflow steps carry `workflow_id` / `workflow_step_id`; resolving `POST /approvals/{id}/approve|deny` updates the linked workflow (resume or cancel).

## Notifications

Auth header `X-User-Id` (development).

- `GET /notifications` — Query `unacked_only` (bool), `limit` (1–200). Response **`{ items: NotificationOut[] }`** (`channel`, **`title`**, **`body`**, **`payload`**, **`acknowledged`**, **`created_at`**).
- `POST /notifications/{notification_id}/ack` — Marks one row acknowledged; **`404`** if not found for user.
- `GET /notifications/rules` — Lists proactive **`ProactiveRule`** rows for the user; **first GET** seeds a default **`daily_digest`** rule (**`ensure_default_digest_rule`**).
- `POST /notifications/rules` — Body **`ProactiveRuleCreate`** (**`title`**, **`rule_type`**, **`interval_minutes`** 5–10080 minutes).
- `PATCH /notifications/rules/{rule_id}` — Body **`enabled`**, **`interval_minutes`** (optional).
- `POST /notifications/dispatch` — Runs the synchronous proactive tick (same evaluation as **`friday.tasks.proactive_tick`**) immediately; returns **`{ status, notifications_created, rules_evaluated }`**. Periodic runs: Celery beat schedule on **`celery_app`** (**every 5 minutes**) plus **`./scripts/run_celery_beat.sh`**.

## Smart home stubs (Phase 11)

Auth header `X-User-Id` (development).

- `GET /smart-home/devices` — Stub catalog merged with Postgres **`smart_home_overrides`** snapshots. Response **`{ items: [...] }`** (`SmartHomeDeviceOut`: **`device_key`**, **`name`**, **`room`**, **`kind`**, **`state`**).
- `GET /smart-home/devices/{device_key}` — **`404`** when **`device_key`** is not part of the in-repo catalog (real hubs replace this seam later).
- `PATCH /smart-home/devices/{device_key}` — Body **`SmartHomeDevicePatch`** — **`state`** shallow/deep merges into the persisted snapshot (`JSONB`).
- Planner tools: **`smarthome.list_devices`**, **`smarthome.set_device_state`** — same backing service as REST; surfaced on **`GET /tools`**.

Web: **`apps/web`** → **`/integrations`** toggle shelf for switches / lights / lock (temperature shown read-only).

## Documents (RAG)

Auth header `X-User-Id` (development). UTF-8 `.txt`-style payloads only for this slice.

- `POST /documents/upload` — `multipart/form-data`: field `file` (text/* or `application/octet-stream`), optional `title`. Chunks text, mocks embeddings, writes `documents` + `document_chunks` with pgvector cosine search.
- `GET /documents` — List current user docs with **`chunk_count`**.
- `GET /documents/{id}` and `GET /documents/{id}/status` — **`status`** (`ready`/`processing`), title, **`chunk_count`**.
- `POST /documents/query` — Body `{ "query": string, "limit"?: number }` → **`answer`** + **`citations`** (scored chunk excerpts tied to **`document_id`**).

Tool **`documents.ask`** (orchestration) invokes the same retrieval path with `query` plus injected `user_id` from **`ToolInvocation`**.

## WebSocket

- `GET /ws/v1/sessions/{session_id}` — Bidirectional chat + assistant status events.

Auth (development): send header `X-User-Id`, or pass `?user_id=` (required for browser-based WebSocket clients without custom headers). Production should terminate TLS and forward stable identity from an edge session.

Event envelope examples:

```json
{ "type": "status", "phase": "checking_calendar", "detail": { "tool": "calendar.read_events" }, "trace_id": "uuid" }
```

```json
{ "type": "conversation.user", "data": { "id": "uuid", "content": "…" }, "trace_id": "uuid" }
```

```json
{ "type": "assistant.delta", "data": { "text": "streaming token chunk" } }
```

```json
{ "type": "assistant.message", "data": { "id": "uuid", "content": "…", "meta": {} } }
```

Client frames:

- `{"type":"ping"}` — pong.
- `{"type":"user_message","text":"..."}`
- `{"type":"voice.session_start","locale":"en-US"}` — server **`voice.ready`** includes **`hint`**, **`server_stt`** (truthy when API key configured or deterministic pytest stubs), **`max_audio_bytes`**, and echoed locale.
- `{"type":"voice.audio","data":"<base64>","mime":"audio/webm","filename":"clip.webm"}` — uploads a short blob for the same Whisper path as **`/transcribe`**; emits the normal thinking → delta → assistant flow after transcription.

After user-visible text arrives (either directly or via `voice.audio`), synthesis may emit **`assistant.delta`** chunks followed by **`assistant.message`** with full **`meta`**.
