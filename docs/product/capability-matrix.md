# Capability Matrix (Consolidated)

See [vision.md](./vision.md) for narrative. Matrix below tracks **implementation status** in-repo.

| Area | Component | Status |
|------|-----------|--------|
| Core | WebSocket chat | Phase 1 |
| Core | REST session/message | Phase 1 |
| Core | Provider abstraction (LLM/embed/vision) | Phase 1 |
| Memory | Four memory types + expiry | Phase 3 |
| Tools | Registry + gateway + policy | Phase 4 |
| Agents | Intent + planner + context | Phase 5 |
| RAG | Chunk + vector + citations | Phase 6 |
| Workflows | State machine + approvals | **Done (Phase 7)** |
| Voice | Web Speech + server STT hints | **Partial** — REST **`/transcribe`**, WebSocket **`voice.audio`**, **`voice.ready.server_stt`**, UI MediaRecorder uploads |
| Voice | Phrase wake + Coqui TTS | **Done (prototype)** — mic clips → **`POST /speech/coqui/wake-scan`** (STT + **`FRIDAY_WAKE_PHRASES`**); TTS via **`POST /speech/coqui/tts`** with **`COQUI_TTS_BACKEND=remote`** (legacy Studio HTTP) or **`COQUI_TTS_BACKEND=local_http`** and the **`services/coqui-local-tts`** sidecar (**`COQUI_SPEAKER_WAV`** on that process). Web: **`NEXT_PUBLIC_USE_COQUI_TTS=1`**. |
| Voice | Full-duplex Realtime speech | **Done (prototype)** — OpenAI **`/v1/realtime/calls`** bridged via **`POST /sessions/{id}/realtime/webrtc`**; browser **`RTCPeerConnection`** + **`oai-events`** data channel (`apps/web/src/lib/fridayRealtimeWebrtc.ts`). |
| Voice | WebRTC + realtime abstraction | **Superseded note** — use **Full-duplex Realtime speech** row above for OpenAI Realtime; additional provider bridges TBD. |
| Desktop | Tauri/Electron shell | **Done (Phase 8)** — Electron `apps/desktop` |
| Developer | Readiness · OpenAPI artifact · `/dev` shell | **Done (Phase 9)** |
| Proactive | Notifications + schedules | **Done (Phase 10)** — in-app **`notifications`** + **`proactive_rules`**; **`POST …/notifications/dispatch`**; Celery **`friday.tasks.proactive_tick`** |
| Smart home | Stub hub + devices REST | **Done (Phase 11)** — **`/smart-home/devices`**, tools **`smarthome.*`**, **`/integrations`** UI |
| Testing & CI | Coverage + contract smoke | **Done (Phase 12)** — pytest-cov **`services/api`**; Vitest **`apps/web`**; **`scripts/run-api-tests.sh`**; **`/.github/workflows/ci.yml`** |
| Observability | OpenTelemetry + local collector | **Done (Phase 13)** — OTLP HTTP (FastAPI/SQLAlchemy/httpx), Compose **`otel-collector`**, **`GET /api/v1/meta.observability`**, see **`docs/architecture/opentelemetry.md`** |
| Personal OS | Streaming LLM + sandboxed host tools | **In progress** — orchestration over WebSocket **`assistant.delta`** + SSE; **OpenAI Realtime WebRTC** (`/realtime/webrtc`, `RealtimeDuplexPanel`); **phrase wake** (Coqui path / STT); **`local.*`** host tools; browser TTS/Mic/Whisper uploads in **`apps/web`**. |

Update this table as features land.
