"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { apiBase } from "@/lib/config";
import type { Phase } from "@/store/friday";

type WsInbound =
  | { type: "status"; phase: string; detail?: Record<string, unknown>; trace_id?: string }
  | {
      type: "conversation.user";
      data: { id: string; session_id?: string; content: string };
      trace_id?: string;
    }
  | { type: "assistant.delta"; data: { text: string } }
  | { type: "assistant.message"; data: { id: string; content: string; meta?: unknown } }
  | { type: "pong" }
  | { type: "voice.ready" }
  | { type: "error"; detail?: string };

function mapServerPhase(phase: string): Phase {
  const allowed: Phase[] = [
    "idle",
    "listening",
    "thinking",
    "checking_calendar",
    "reading_documents",
    "checking_email",
    "executing",
    "waiting_approval",
    "synthesizing_response",
    "done",
    "error",
  ];
  return (allowed.includes(phase as Phase) ? phase : "thinking") as Phase;
}

export type FridaySocketHandlers = {
  userId: string | null;
  sessionId: string | null;
  onPhase: (p: Phase, detail?: Record<string, unknown>) => void;
  onUserCommitted: (id: string, content: string) => void;
  onAssistantDelta: (delta: string) => void;
  onAssistantMessage: (content: string, meta?: unknown) => void;
  onToolMeta: (meta: unknown) => void;
};

export function useFridaySocket(handlers: FridaySocketHandlers) {
  const wsRef = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const r = useRef(handlers);
  r.current = handlers;

  const disconnect = useCallback(() => {
    wsRef.current?.close();
    wsRef.current = null;
    setConnected(false);
  }, []);

  const connect = useCallback(() => {
    const { userId, sessionId } = r.current;
    if (!userId || !sessionId) return;
    disconnect();
    const u = new URL(apiBase);
    const proto = u.protocol === "https:" ? "wss:" : "ws:";
    const url = `${proto}//${u.host}/ws/v1/sessions/${sessionId}?user_id=${encodeURIComponent(userId)}`;
    const ws = new WebSocket(url);
    wsRef.current = ws;
    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);
    ws.onerror = () => r.current.onPhase("error");
    ws.onmessage = (ev) => {
      try {
        const raw = JSON.parse(String(ev.data)) as WsInbound;
        if (raw.type === "status" && raw.phase) {
          r.current.onPhase(mapServerPhase(raw.phase), raw.detail);
        }
        if (raw.type === "conversation.user") {
          r.current.onUserCommitted(raw.data.id, raw.data.content);
        }
        if (raw.type === "assistant.delta" && raw.data?.text) {
          r.current.onAssistantDelta(raw.data.text);
        }
        if (raw.type === "assistant.message") {
          r.current.onAssistantMessage(raw.data.content, raw.data.meta);
          if (raw.data.meta) {
            r.current.onToolMeta(raw.data.meta);
          }
        }
      } catch {
        r.current.onPhase("error");
      }
    };
  }, [disconnect]);

  const sendUserMessage = useCallback((text: string) => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return false;
    ws.send(JSON.stringify({ type: "user_message", text }));
    return true;
  }, []);

  const sendVoiceSessionStart = useCallback(() => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify({ type: "voice.session_start", locale: navigator.language || "en-US" }));
  }, []);

  useEffect(() => () => disconnect(), [disconnect]);

  return { connect, disconnect, connected, sendUserMessage, sendVoiceSessionStart };
}
