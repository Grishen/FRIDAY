"use client";

import { useCallback, useRef, useState } from "react";
import { negotiateFridayRealtimeDuplex } from "@/lib/fridayRealtimeWebrtc";

export type RealtimeDuplexPanelProps = {
  userId: string | null;
  sessionId: string | null;
  onEnsureSession: () => Promise<string | null>;
  className?: string;
};

const DEFAULT_BUILTIN = "Jarvis";

export function RealtimeDuplexPanel(props: RealtimeDuplexPanelProps) {
  const { userId } = props;
  const busyRef = useRef(false);
  const armRef = useRef<{ disarm: () => Promise<void> } | null>(null);
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const stopTracksRef = useRef<(() => void) | null>(null);

  const [wakeArmed, setWakeArmed] = useState(false);
  const [duplexBusy, setDuplexBusy] = useState(false);
  const [logLine, setLogLine] = useState("");
  const [lastTranscript, setLastTranscript] = useState("");

  const accessKey =
    typeof process.env.NEXT_PUBLIC_PICOVOICE_ACCESS_KEY === "string"
      ? process.env.NEXT_PUBLIC_PICOVOICE_ACCESS_KEY.trim()
      : "";
  const builtinName =
    typeof process.env.NEXT_PUBLIC_WAKE_BUILTIN === "string" &&
    process.env.NEXT_PUBLIC_WAKE_BUILTIN.trim().length > 0
      ? process.env.NEXT_PUBLIC_WAKE_BUILTIN.trim()
      : DEFAULT_BUILTIN;

  const stopDuplex = useCallback(() => {
    stopTracksRef.current?.();
    stopTracksRef.current = null;
    pcRef.current?.getSenders().forEach((s) => s.track?.stop());
    pcRef.current?.close();
    pcRef.current = null;
    busyRef.current = false;
    setDuplexBusy(false);
  }, []);

  const stopWake = useCallback(async () => {
    if (armRef.current) {
      await armRef.current.disarm().catch(() => undefined);
      armRef.current = null;
    }
    setWakeArmed(false);
    const mod = await import("@picovoice/web-voice-processor").catch(() => null);
    await mod?.WebVoiceProcessor.reset().catch(() => undefined);
  }, []);

  const startDuplexOnce = useCallback(async () => {
    if (!userId) return;
    if (busyRef.current) return;
    const sid = props.sessionId ?? (await props.onEnsureSession());
    if (!sid) return;

    busyRef.current = true;
    setDuplexBusy(true);
    setLogLine("Negotiating WebRTC with OpenAI Realtime…");

    await stopWake().catch(() => undefined);

    try {
      const { pc, dataChannel, stopTracks } = await negotiateFridayRealtimeDuplex({
        sessionId: sid,
        userId,
      });
      pcRef.current = pc;
      stopTracksRef.current = stopTracks;

      pc.onconnectionstatechange = () => setLogLine(`Peer: ${pc.connectionState}`);
      dataChannel.onmessage = (ev) => {
        try {
          const msg = JSON.parse(String(ev.data)) as Record<string, unknown>;
          const t = typeof msg.type === "string" ? msg.type : "";
          const chunkCandidate =
            typeof (msg as { delta?: unknown }).delta === "string"
              ? ((msg as { delta: string }).delta as string)
              : typeof (msg as { transcript?: unknown }).transcript === "string"
                ? ((msg as { transcript: string }).transcript as string)
                : "";
          if (
            chunkCandidate &&
            (t.includes("delta") || t.endsWith("completed") || t.endsWith("_done"))
          ) {
            setLastTranscript((p) => (p + chunkCandidate).slice(-2400));
          }
        } catch {
          /* non-json */
        }
      };
      setLogLine("Realtime duplex audio connected — speak freely. Press Stop when done.");
    } catch (e) {
      setLogLine(`Failed: ${e instanceof Error ? e.message : String(e)}`);
      stopDuplex();
    }
  }, [props, stopDuplex, stopWake, userId]);

  const toggleWakeArm = async () => {
    if (!userId || !accessKey) return;
    if (wakeArmed) {
      await stopWake();
      setLogLine("Wake listening stopped.");
      return;
    }
    if (duplexBusy) stopDuplex();

    setLogLine("Loading Porcupine WASM…");
    const { armPorcupineWakeWordBuiltin } = await import("@/lib/wakePorcupine");
    try {
      armRef.current = await armPorcupineWakeWordBuiltin(accessKey, builtinName, async () => {
        setLogLine("Wake phrase detected → starting realtime duplex.");
        await startDuplexOnce();
      });
      setWakeArmed(true);
      setLogLine(`Wake armed (${builtinName}) — say the Porcupine built-in phrase.`);
    } catch (e) {
      setLogLine(`Wake init failed: ${e instanceof Error ? e.message : String(e)}`);
      await stopWake().catch(() => undefined);
    }
  };

  return (
    <div
      className={
        props.className ??
        "space-y-2 rounded-xl border border-blue-400/25 bg-blue-950/30 px-3 py-3"
      }
    >
      <p className="text-xs font-semibold uppercase tracking-wide text-blue-300">
        Full-duplex audio (WebRTC ↔ OpenAI Realtime)
      </p>
      <p className="text-[11px] leading-relaxed text-zinc-400">
        True bidirectional voice uses your mic as a peer track and streams model speech back automatically. Planner tools
        (`local.*`, approvals) are **not** in this lane yet — use text/WebSocket orchestration when you need governed
        tools.
      </p>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          disabled={!userId}
          className="rounded-md bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-blue-500 disabled:opacity-40"
          onClick={() => void startDuplexOnce()}
        >
          Start duplex (WebRTC)
        </button>
        <button
          type="button"
          disabled={!duplexBusy}
          className="rounded-md border border-white/15 px-3 py-1.5 text-xs text-zinc-200 hover:bg-white/5 disabled:opacity-40"
          onClick={stopDuplex}
        >
          Stop
        </button>
        <button
          type="button"
          disabled={!userId || !accessKey}
          title={
            accessKey
              ? "Picovoice Porcupine WASM — always-listening keyword"
              : "Set NEXT_PUBLIC_PICOVOICE_ACCESS_KEY"
          }
          className={`rounded-md px-3 py-1.5 text-xs font-semibold disabled:opacity-40 ${
            wakeArmed ? "bg-amber-600 text-white" : "border border-white/15 text-zinc-200 hover:bg-white/5"
          }`}
          onClick={() => void toggleWakeArm()}
        >
          {wakeArmed ? "Disarm Porcupine" : "Arm wake (Porcupine)"}
        </button>
      </div>
      {!accessKey ? (
        <p className="text-[11px] text-amber-100/85">
          For <strong>true wake word</strong> in-browser, obtain a Picovoice access key and set
          NEXT_PUBLIC_PICOVOICE_ACCESS_KEY. Optional NEXT_PUBLIC_WAKE_BUILTIN (default Jarvis).
        </p>
      ) : null}
      <p className="truncate font-mono text-[11px] text-zinc-500">{logLine || "Idle."}</p>
      {lastTranscript ? (
        <pre className="max-h-24 overflow-auto rounded bg-black/40 p-2 text-[11px] text-blue-100/90">
          {lastTranscript}
        </pre>
      ) : null}
    </div>
  );
}
