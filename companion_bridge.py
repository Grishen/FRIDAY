"""HTTP companion bridge for phone / watch / Shortcuts.

Lightweight JSON API so a mobile client can ask questions and trigger sync
without the full voice loop. Auth via ``JARVIS_COMPANION_TOKEN`` header.

Endpoints:
    GET  /v1/health
    POST /v1/ask     {"text": "..."}  → {"reply": "..."}
    POST /v1/sync    → {"message": "..."}
    GET  /v1/status  → privacy + sync summary

Env:
    JARVIS_COMPANION=1
    JARVIS_COMPANION_HOST=127.0.0.1
    JARVIS_COMPANION_PORT=8765
    JARVIS_COMPANION_TOKEN=your-secret
"""

from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Optional

_ASK_HANDLER: Optional[Callable[[str], str]] = None
_SERVER: Optional[ThreadingHTTPServer] = None
_THREAD: Optional[threading.Thread] = None


def enabled() -> bool:
    return os.environ.get("JARVIS_COMPANION", "0").strip().lower() in (
        "1", "true", "yes", "on",
    )


def register_ask_handler(fn: Callable[[str], str]) -> None:
    global _ASK_HANDLER
    _ASK_HANDLER = fn


def _token_ok(headers) -> bool:
    expected = os.environ.get("JARVIS_COMPANION_TOKEN", "").strip()
    if not expected:
        return True  # local-only default; set a token for LAN exposure
    got = (headers.get("X-Jarvis-Token") or headers.get("Authorization") or "").strip()
    if got.lower().startswith("bearer "):
        got = got[7:].strip()
    return got == expected


def _json_response(handler: BaseHTTPRequestHandler, code: int, payload: dict) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class _CompanionHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:  # noqa: ARG002
        return  # quiet by default

    def do_GET(self) -> None:  # noqa: N802
        if not _token_ok(self.headers):
            _json_response(self, 401, {"error": "unauthorized"})
            return
        if self.path.rstrip("/") in ("/v1/health", "/health"):
            _json_response(self, 200, {"ok": True, "service": "jarvis-companion"})
            return
        if self.path.rstrip("/") == "/v1/status":
            bits: dict = {"ok": True}
            try:
                from privacy import describe_privacy_state

                bits["privacy"] = describe_privacy_state()
            except Exception:
                bits["privacy"] = "unknown"
            try:
                from sync_service import describe_sync_status

                bits["sync"] = describe_sync_status()
            except Exception:
                bits["sync"] = "unknown"
            _json_response(self, 200, bits)
            return
        _json_response(self, 404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if not _token_ok(self.headers):
            _json_response(self, 401, {"error": "unauthorized"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            _json_response(self, 400, {"error": "invalid json"})
            return

        path = self.path.rstrip("/")
        if path == "/v1/ask":
            text = str(body.get("text") or "").strip()
            if not text:
                _json_response(self, 400, {"error": "text required"})
                return
            if not _ASK_HANDLER:
                _json_response(self, 503, {"error": "ask handler not registered"})
                return
            try:
                reply = _ASK_HANDLER(text)
            except Exception as exc:  # noqa: BLE001
                _json_response(self, 500, {"error": str(exc)})
                return
            _json_response(self, 200, {"reply": reply})
            return

        if path == "/v1/sync":
            try:
                from sync_service import sync_now

                msg = sync_now()
            except Exception as exc:  # noqa: BLE001
                _json_response(self, 500, {"error": str(exc)})
                return
            _json_response(self, 200, {"message": msg})
            return

        _json_response(self, 404, {"error": "not found"})


def is_running() -> bool:
    return bool(_THREAD and _THREAD.is_alive())


def stop_companion_server() -> None:
    global _SERVER, _THREAD
    srv = _SERVER
    if srv:
        try:
            srv.shutdown()
        except Exception:
            pass
    t = _THREAD
    if t and t.is_alive():
        t.join(timeout=2.0)
    _SERVER = None
    _THREAD = None


def start_companion_server() -> bool:
    global _SERVER, _THREAD
    if not enabled():
        return False
    if is_running():
        return True
    host = os.environ.get("JARVIS_COMPANION_HOST", "127.0.0.1").strip() or "127.0.0.1"
    try:
        port = int(os.environ.get("JARVIS_COMPANION_PORT", "8765"))
    except (TypeError, ValueError):
        port = 8765
    try:
        _SERVER = ThreadingHTTPServer((host, port), _CompanionHandler)
    except Exception as exc:
        print(f"[companion] failed to bind {host}:{port}: {exc}", flush=True)
        return False
    _THREAD = threading.Thread(target=_SERVER.serve_forever, name="jarvis-companion", daemon=True)
    _THREAD.start()
    print(f"[startup] Companion API: http://{host}:{port}/v1/health", flush=True)
    return True


__all__ = [
    "enabled",
    "is_running",
    "register_ask_handler",
    "start_companion_server",
    "stop_companion_server",
]
