"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { VoicePanel, type VoicePanelRef, type VoiceSttMode } from "@/components/VoicePanel";
import { apiFetch } from "@/lib/api";
import { postSessionMessageStream } from "@/lib/chatStream";
import { speakFriday } from "@/lib/fridayTts";
import { transcribeSessionAudio } from "@/lib/transcribeApi";
import { useFridaySocket } from "@/hooks/useFridaySocket";
import { ApprovalModal } from "@/components/ApprovalModal";
import { RealtimeDuplexPanel } from "@/components/RealtimeDuplexPanel";
import { Phase, useFridayStore } from "@/store/friday";

const STATUS_LABEL: Record<Phase, string> = {
  idle: "Idle",
  listening: "Listening",
  thinking: "Thinking",
  checking_calendar: "Checking calendar",
  reading_documents: "Reading documents",
  checking_email: "Checking email",
  executing: "Executing tool",
  waiting_approval: "Waiting approval",
  synthesizing_response: "Synthesizing",
  done: "Done",
  error: "Error",
};

export default function Home() {
  const {
    userId,
    sessionId,
    messages,
    phase,
    streamingAssistant,
    pendingApprovalId,
    pendingApprovalTool,
    toolLines,
    speakAssistantReplies,
    setUserId,
    setSessionId,
    setPhase,
    appendMessage,
    appendAssistantDelta,
    resetStreamingAssistant,
    setSpeakAssistantReplies,
    setToolLines,
    setApprovalPrompt,
    clearChat,
  } = useFridayStore();
  const [input, setInput] = useState("");
  const [sttMode, setSttMode] = useState<VoiceSttMode>("browser");
  const [duplexLiteMic, setDuplexLiteMic] = useState(false);
  const [approvalBusy, setApprovalBusy] = useState(false);
  const [approvalError, setApprovalError] = useState<string | null>(null);
  const approvalIdRef = useRef<string | null>(null);
  const voiceRef = useRef<VoicePanelRef>(null);

  const banner = useMemo(
    () => "FRIDAY · Personal AI Operating System",
    [],
  );

  const bootstrap = useCallback(async () => {
    const res = (await apiFetch("/api/v1/auth/bootstrap", {
      method: "POST",
      body: JSON.stringify({ email: "user@example.com" }),
    })) as { user_id: string };
    setUserId(res.user_id);
  }, [setUserId]);

  useEffect(() => {
    if (!userId) void bootstrap();
  }, [bootstrap, userId]);

  const ensureSession = useCallback(async () => {
    if (!userId) return null;
    if (sessionId) return sessionId;
    const s = (await apiFetch("/api/v1/sessions", {
      method: "POST",
      body: JSON.stringify({ title: "Main" }),
      userId,
    })) as { id: string };
    setSessionId(s.id);
    return s.id;
  }, [sessionId, setSessionId, userId]);

  const socketHandlers = useMemo(
    () => ({
      userId,
      sessionId,
      onPhase: (p: Phase, detail?: Record<string, unknown>) => {
        setPhase(p);
        if (p === "waiting_approval" && detail) {
          const rawAid = detail.approval_id;
          const aid = rawAid == null ? "" : String(rawAid).trim();
          const tool = detail.tool;
          if (aid) {
            setApprovalPrompt(aid, typeof tool === "string" ? tool : null);
          }
        }
      },
      onUserCommitted: (id: string, content: string) =>
        appendMessage({ role: "user", content, id }),
      onAssistantDelta: (delta: string) => {
        appendAssistantDelta(delta);
      },
      onAssistantMessage: (content: string, meta?: unknown) => {
        resetStreamingAssistant();
        appendMessage({ role: "assistant", content });
        if (useFridayStore.getState().speakAssistantReplies) {
          speakFriday(content, {
            userId,
            onEnd:
              duplexLiteMic && sttMode === "browser"
                ? () => voiceRef.current?.kickAfterAssistantSpeak()
                : undefined,
          });
        }
        if (meta && typeof meta === "object" && meta !== null && "tools" in meta) {
          const tools = (
            meta as {
              tools?: { status?: string; tool?: string; envelope?: { approval_id?: string } }[];
            }
          ).tools;
          const pend = tools?.find(
            (t) => t.status === "pending_approval" && t.envelope && t.envelope.approval_id,
          );
          if (pend?.envelope?.approval_id) {
            setApprovalPrompt(String(pend.envelope.approval_id), pend.tool ?? null);
            setPhase("waiting_approval");
          }
        }
      },
      onToolMeta: (meta: unknown) => {
        const toolSummary = JSON.stringify(meta, null, 2);
        setToolLines(toolSummary.split("\n").slice(0, 48));
      },
    }),
    [
      appendMessage,
      appendAssistantDelta,
      duplexLiteMic,
      resetStreamingAssistant,
      sessionId,
      setApprovalPrompt,
      setPhase,
      setToolLines,
      sttMode,
      userId,
    ],
  );

  approvalIdRef.current = pendingApprovalId;

  const resolveApproval = useCallback(
    async (decision: "approve" | "deny") => {
      const id = approvalIdRef.current ?? pendingApprovalId;
      if (!userId || !id) return;
      setApprovalBusy(true);
      setApprovalError(null);
      try {
        await apiFetch(`/api/v1/approvals/${id}/resolve`, {
          method: "POST",
          userId,
          body: JSON.stringify({ decision, reason: decision === "deny" ? "user denied in UI" : null }),
        });
        setApprovalPrompt(null, null);
        setPhase("done");
        appendMessage({
          role: "assistant",
          content:
            decision === "approve"
              ? "Approval recorded — mocked tool queued for Celery execution (audit log updated)."
              : "Denial recorded — tool call cancelled (audit log updated).",
        });
      } catch (e) {
        setApprovalError(String(e));
      } finally {
        setApprovalBusy(false);
      }
    },
    [appendMessage, pendingApprovalId, setApprovalPrompt, setPhase, userId],
  );

  const { connect, disconnect, connected, sendUserMessage, sendVoiceSessionStart } =
    useFridaySocket(socketHandlers);

  useEffect(() => {
    if (!userId || !sessionId) {
      disconnect();
      return undefined;
    }
    connect();
    return () => disconnect();
  }, [connect, disconnect, sessionId, userId]);

  useEffect(() => {
    if (connected && sessionId && userId) sendVoiceSessionStart();
  }, [connected, sessionId, userId, sendVoiceSessionStart]);

  const transcribeUploader = useCallback(
    async (blob: Blob) => {
      const sid = sessionId ?? (await ensureSession());
      if (!userId || !sid) throw new Error("missing ids");
      return transcribeSessionAudio(sid, blob, userId);
    },
    [ensureSession, sessionId, userId],
  );

  const dispatchMessage = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed) return;
      resetStreamingAssistant();
      const sid = await ensureSession();
      if (!userId || !sid) return;

      setPhase("thinking");

      const viaSocket = sendUserMessage(trimmed);
      if (!viaSocket) {
        appendMessage({ role: "user", content: trimmed });
        try {
          await postSessionMessageStream(sid, trimmed, userId, {
            onDelta: (d: string) => appendAssistantDelta(d),
            onAssistantFinal: (content: string, meta: unknown) => {
              resetStreamingAssistant();
              const summary = JSON.stringify(meta ?? {}, null, 2);
              setToolLines(summary.split("\n").slice(0, 48));
              appendMessage({ role: "assistant", content });
              setPhase("done");
              if (useFridayStore.getState().speakAssistantReplies) {
                speakFriday(content, {
                  userId,
                  onEnd:
                    duplexLiteMic && sttMode === "browser"
                      ? () => voiceRef.current?.kickAfterAssistantSpeak()
                      : undefined,
                });
              }
            },
          });
        } catch {
          try {
            const assistant = (await apiFetch(`/api/v1/sessions/${sid}/messages`, {
              method: "POST",
              body: JSON.stringify({ content: trimmed }),
              userId,
            })) as { content: string; meta?: unknown };
            resetStreamingAssistant();
            const summary = JSON.stringify(assistant.meta ?? {}, null, 2);
            setToolLines(summary.split("\n").slice(0, 48));
            appendMessage({ role: "assistant", content: assistant.content });
            setPhase("done");
            if (useFridayStore.getState().speakAssistantReplies) {
              speakFriday(assistant.content, {
                userId,
                onEnd:
                  duplexLiteMic && sttMode === "browser"
                    ? () => voiceRef.current?.kickAfterAssistantSpeak()
                    : undefined,
              });
            }
          } catch {
            resetStreamingAssistant();
            setPhase("error");
          }
        }
      }
    },
    [
      appendAssistantDelta,
      appendMessage,
      duplexLiteMic,
      ensureSession,
      resetStreamingAssistant,
      sendUserMessage,
      setPhase,
      setToolLines,
      sttMode,
      userId,
    ],
  );

  const sendRest = async () => {
    const text = input;
    setInput("");
    await dispatchMessage(text);
  };

  const onVoiceFinal = async (spoken: string) => {
    setPhase("listening");
    await dispatchMessage(spoken);
  };

  return (
    <div className="min-h-screen bg-gradient-to-b from-zinc-950 to-black text-zinc-100">
      <header className="border-b border-white/5 bg-black/40 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4">
          <div>
            <p className="text-xs uppercase tracking-[0.2em] text-emerald-400">Friday</p>
            <h1 className="text-xl font-semibold">{banner}</h1>
          </div>
          <nav className="flex flex-wrap gap-3 text-sm text-zinc-300">
            <Link className="hover:text-white" href="/memory">
              Memory
            </Link>
            <Link className="hover:text-white" href="/documents">
              Documents
            </Link>
            <Link className="hover:text-white" href="/integrations">
              Integrations
            </Link>
            <Link className="hover:text-white" href="/workflows">
              Workflows
            </Link>
            <Link className="hover:text-white" href="/notifications">
              Notifications
            </Link>
            <Link className="hover:text-white" href="/dev">
              Dev
            </Link>
            <Link className="hover:text-white" href="/debug">
              Debug
            </Link>
          </nav>
        </div>
      </header>

      <main className="mx-auto grid max-w-7xl gap-4 px-4 py-6 lg:grid-cols-[2fr_1fr]">
        <section className="space-y-4 rounded-2xl border border-white/10 bg-zinc-950/60 p-4 shadow-xl shadow-emerald-500/5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-sm text-zinc-400">Assistant</p>
              <p className="text-lg font-medium text-white">Main console</p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded-full bg-white/5 px-3 py-1 text-xs text-emerald-300 ring-1 ring-emerald-500/30">
                {STATUS_LABEL[phase]}
              </span>
              <span
                className={`rounded-full px-2 py-0.5 text-[11px] ${connected ? "bg-emerald-500/10 text-emerald-200" : "bg-white/5 text-zinc-400"}`}
              >
                {connected ? "Realtime on" : "Realtime off"}
              </span>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              className="rounded-md border border-white/10 px-3 py-1.5 text-sm hover:bg-white/5"
              onClick={() => clearChat()}
            >
              Clear transcript (local)
            </button>
            <label className="flex cursor-pointer items-center gap-2 text-xs text-zinc-400">
              <input
                type="checkbox"
                className="rounded border-white/20"
                checked={speakAssistantReplies}
                onChange={(ev) => setSpeakAssistantReplies(ev.target.checked)}
              />
              Speak replies (browser TTS)
            </label>
            <label className="flex cursor-pointer items-center gap-2 text-xs text-zinc-400">
              <input
                type="checkbox"
                className="rounded border-white/20"
                checked={duplexLiteMic}
                onChange={(ev) => setDuplexLiteMic(ev.target.checked)}
              />
              Duplex-lite (12s mic after FRIDAY speaks)
            </label>
            <label className="flex items-center gap-2 text-xs text-zinc-400">
              <span className="text-zinc-500">STT</span>
              <select
                className="rounded border border-white/15 bg-zinc-950 px-2 py-1 text-xs text-zinc-100"
                value={sttMode}
                onChange={(ev) => setSttMode(ev.target.value as VoiceSttMode)}
              >
                <option value="browser">Browser speech</option>
                <option value="server">Server Whisper</option>
              </select>
            </label>
          </div>

          <div className="space-y-3 rounded-xl bg-black/30 p-4 ring-1 ring-white/5 min-h-[320px] max-h-[480px] overflow-y-auto">
            {messages.length === 0 ? (
              <div className="space-y-3 text-sm text-zinc-400">
                <p>
                  Ask anything or use voice. With realtime off, REST uses SSE streaming for tokens; with realtime on,
                  WebSocket streams deltas. Hold-to-talk supports browser STT or server Whisper uploads; optional
                  duplex-lite reopens the mic for ~12s after FRIDAY finishes speaking.
                </p>
                <p>
                  Example:&nbsp;
                  <button
                    type="button"
                    className="text-left font-medium text-white underline underline-offset-2"
                    onClick={() =>
                      dispatchMessage("Friday — prepare me for tomorrow and send recap if needed.")
                    }
                  >
                    Friday, prepare me for tomorrow.
                  </button>{" "}
                  To exercise <strong className="text-white">approvals</strong>, include the word{" "}
                  <strong className="text-white">send</strong> ( planner routes to mocked{" "}
                  <code className="text-emerald-300">email.send</code>).
                </p>
              </div>
            ) : (
              messages.map((m, idx) => (
                <div key={idx} className="rounded-lg border border-white/5 bg-white/5 p-3">
                  <p className="text-[11px] uppercase tracking-wide text-emerald-300">{m.role}</p>
                  <p className="mt-2 whitespace-pre-wrap text-sm text-zinc-100">{m.content}</p>
                </div>
              ))
            )}
            {streamingAssistant ? (
              <div className="rounded-lg border border-dashed border-amber-500/50 bg-amber-950/20 p-3">
                <p className="text-[11px] uppercase tracking-wide text-amber-300">assistant streaming</p>
                <p className="mt-2 whitespace-pre-wrap text-sm text-amber-50">{streamingAssistant}</p>
              </div>
            ) : null}
          </div>

          <VoicePanel
            ref={voiceRef}
            disabled={!userId}
            connected={connected}
            sttMode={sttMode}
            transcribeUploader={sttMode === "server" ? transcribeUploader : undefined}
            onListeningChange={(listening) => {
              if (listening) setPhase("listening");
            }}
            onFinalText={(t) => void onVoiceFinal(t)}
          />

          <RealtimeDuplexPanel
            userId={userId}
            sessionId={sessionId}
            onEnsureSession={ensureSession}
          />

          <div className="flex flex-col gap-3 md:flex-row">
            <textarea
              className="min-h-[90px] flex-1 rounded-xl border border-white/10 bg-zinc-950/80 px-3 py-2 text-sm outline-none ring-emerald-500/40 focus:border-emerald-500/70"
              placeholder="Message FRIDAY..."
              value={input}
              onChange={(e) => setInput(e.target.value)}
            />
            <button
              type="button"
              className="h-11 rounded-xl bg-emerald-600 px-6 text-sm font-semibold text-white shadow-lg shadow-emerald-600/40 transition hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-40"
              onClick={() => void sendRest()}
              disabled={!userId}
            >
              Send
            </button>
          </div>
        </section>

        <aside className="space-y-4">
          <div className="rounded-2xl border border-white/10 bg-zinc-950/60 p-4">
            <div className="flex items-center justify-between">
              <p className="text-sm font-medium text-white">RAG & uploads</p>
              <span className="rounded-full bg-emerald-500/10 px-2 py-0.5 text-[11px] text-emerald-200">
                Phase 6
              </span>
            </div>
            <p className="mt-3 text-xs text-zinc-400">
              <Link href="/documents" className="text-emerald-300 hover:text-white">
                /documents
              </Link>{" "}
              chunks + embeds text; <code className="text-emerald-300">documents.ask</code> in chat runs the same index.
              Planner + memory context still apply on each turn.
            </p>
          </div>
          <div className="rounded-2xl border border-white/10 bg-zinc-950/60 p-4">
            <div className="flex items-center justify-between">
              <p className="text-sm font-medium text-white">Tool activity</p>
              <span className="text-[11px] text-zinc-500">Planner + gateway</span>
            </div>
            <pre className="mt-3 max-h-60 overflow-auto rounded-lg bg-black/40 p-3 text-[11px] text-emerald-200">
              {toolLines.length ? toolLines.join("\n") : "Silent..."}
            </pre>
          </div>
          <div className="rounded-2xl border border-white/10 bg-zinc-950/60 p-4">
            <p className="text-sm font-medium text-white">Session</p>
            <p className="mt-2 break-all text-[11px] text-zinc-400">
              user: {userId ?? "creating..."}
              <br />
              session: {sessionId ?? "not created"}
            </p>
          </div>
        </aside>
      </main>

      <ApprovalModal
        open={!!pendingApprovalId}
        toolName={pendingApprovalTool}
        busy={approvalBusy}
        errorText={approvalError}
        onApprove={() => resolveApproval("approve")}
        onDeny={() => resolveApproval("deny")}
      />
    </div>
  );
}
