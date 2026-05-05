"use client";

import { useCallback, useRef, useState } from "react";
import { postWakePhraseScan } from "@/lib/coquiSpeechApi";
import { negotiateFridayRealtimeDuplex } from "@/lib/fridayRealtimeWebrtc";

export type RealtimeDuplexPanelProps = {
  userId: string | null;
  sessionId: string | null;
  onEnsureSession: () => Promise<string | null>;
  className?: string;
};

/** ~2.8s snippets for STT phrase wake via `/speech/coqui/wake-scan`. */
const DEFAULT_WAKE_CLIP_MS = 2800;

async function captureMediaClip(stream: MediaStream, ms: number): Promise<Blob> {
  const MR = typeof MediaRecorder !== "undefined" ? MediaRecorder : null;
  if (!MR) throw new Error("MediaRecorder unsupported");

  const mimeCandidates = ["audio/webm;codecs=opus", "audio/webm"];
  let mimeType = "";
  for (const candidate of mimeCandidates) {
    try {
      if (MR.isTypeSupported(candidate)) {
        mimeType = candidate;
        break;
      }
    } catch {
      /* MR.isTypeUnsupported in some browsers */
    }
  }

  const rec = mimeType ? new MR(stream, { mimeType }) : new MR(stream);
  const chunks: BlobPart[] = [];

  await new Promise<void>((resolveStarted) => {
    rec.onstart = () => resolveStarted();
    rec.ondataavailable = (ev) => {
      if (ev.data?.size) chunks.push(ev.data);
    };
    rec.start(100);
  });

  await new Promise<void>((resolveStopped) => {
    rec.onstop = () => resolveStopped();
    window.setTimeout(() => {
      try {
        rec.stop();
      } catch {
        resolveStopped();
      }
    }, ms);
  });

  const first = chunks[0];
  const typ =
    typeof Blob !== "undefined" && first instanceof Blob && first.type
      ? first.type
      : rec.mimeType || "audio/webm";
  return new Blob(chunks, { type: typ });
}

export function RealtimeDuplexPanel(props: RealtimeDuplexPanelProps) {
  const { userId } = props;
  const busyRef = useRef(false);
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const stopTracksRef = useRef<(() => void) | null>(null);
  const wakeAbortRef = useRef<AbortController | null>(null);
  const wakeStreamRef = useRef<MediaStream | null>(null);

  const [wakeArmed, setWakeArmed] = useState(false);
  const [duplexBusy, setDuplexBusy] = useState(false);
  const [logLine, setLogLine] = useState("");
  const [lastTranscript, setLastTranscript] = useState("");

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
    wakeAbortRef.current?.abort();
    wakeAbortRef.current = null;
    wakeStreamRef.current?.getTracks().forEach((t) => t.stop());
    wakeStreamRef.current = null;
    setWakeArmed(false);
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
    if (!userId) return;
    if (wakeArmed) {
      await stopWake();
      setLogLine("Phrase wake listening stopped.");
      return;
    }
    if (duplexBusy) stopDuplex();

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      wakeStreamRef.current = stream;
    } catch (e) {
      setLogLine(`Mic denied: ${e instanceof Error ? e.message : String(e)}`);
      return;
    }

    const ac = new AbortController();
    wakeAbortRef.current = ac;
    setWakeArmed(true);
    setLogLine("Listening for wake phrases → sent to `/speech/coqui/wake-scan` (STT)…");

    void (async () => {
      const stream = wakeStreamRef.current;
      if (!stream) return;

      try {
        while (!ac.signal.aborted) {
          let blob: Blob;
          try {
            blob = await captureMediaClip(stream, DEFAULT_WAKE_CLIP_MS);
          } catch (err) {
            if (ac.signal.aborted) break;
            setLogLine(`Wake capture failed: ${err instanceof Error ? err.message : String(err)}`);
            await stopWake();
            return;
          }
          if (ac.signal.aborted) break;

          try {
            const r = await postWakePhraseScan(blob, userId);
            setLastTranscript((p) => (r.text.trim() ? r.text : p));
            if (r.triggered) {
              setLogLine("Wake phrase detected → starting realtime duplex.");
              await stopWake().catch(() => undefined);
              await startDuplexOnce();
              return;
            }
          } catch (err) {
            if (ac.signal.aborted) break;
            setLogLine(`Wake-scan failed: ${err instanceof Error ? err.message : String(err)}`);
            await stopWake();
            return;
          }
        }
      } finally {
        if (!ac.signal.aborted) {
          await stopWake().catch(() => undefined);
        }
      }
    })();
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
          disabled={!userId}
          title="Short mic clips are transcribed; API matches FRIDAY_WAKE_PHRASES (comma-separated)"
          className={`rounded-md px-3 py-1.5 text-xs font-semibold disabled:opacity-40 ${
            wakeArmed ? "bg-amber-600 text-white" : "border border-white/15 text-zinc-200 hover:bg-white/5"
          }`}
          onClick={() => void toggleWakeArm()}
        >
          {wakeArmed ? "Disarm phrase wake" : "Arm phrase wake (Coqui path)"}
        </button>
      </div>
      <p className="text-[11px] text-zinc-500">
        Phrase wake uploads audio to the API (Whisper-class STT today). Configure matches with{" "}
        <code className="text-zinc-400">FRIDAY_WAKE_PHRASES</code> on the server. TTS uses Coqui Studio when{" "}
        <code className="text-zinc-400">COQUI_API_TOKEN</code> + <code className="text-zinc-400">COQUI_VOICE_ID</code>{" "}
        are set; enable the web client with <code className="text-zinc-400">NEXT_PUBLIC_USE_COQUI_TTS=1</code>.
      </p>
      <p className="truncate font-mono text-[11px] text-zinc-500">{logLine || "Idle."}</p>
      {lastTranscript ? (
        <pre className="max-h-24 overflow-auto rounded bg-black/40 p-2 text-[11px] text-blue-100/90">
          {lastTranscript}
        </pre>
      ) : null}
    </div>
  );
}
