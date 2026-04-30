"use client";

import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from "react";

import { stripFridayWakePrefix } from "@/lib/wakePhrase";

function getSpeechCtor(): SpeechRecognitionConstructor | undefined {
  if (typeof window === "undefined") return undefined;
  return window.SpeechRecognition ?? window.webkitSpeechRecognition;
}

export type VoicePanelRef = {
  /** After assistant TTS, open a timed listen window without holding the button. */
  kickAfterAssistantSpeak: () => void;
};

export type VoiceSttMode = "browser" | "server";

type Props = {
  disabled?: boolean;
  connected: boolean;
  userId?: string | null;
  sessionId?: string | null;
  sttMode?: VoiceSttMode;
  wakeStripFriday?: boolean;
  onListeningChange?: (listening: boolean) => void;
  onFinalText: (text: string) => void;
  transcribeUploader?: (blob: Blob) => Promise<string>;
};

export const VoicePanel = forwardRef<VoicePanelRef, Props>(function VoicePanel(props, ref) {
  const {
    sttMode = "browser",
    wakeStripFriday = true,
  } = props;

  const [supported, setSupported] = useState<boolean | null>(null);
  const [mrSupported, setMrSupported] = useState<boolean>(false);
  const [recording, setRecording] = useState(false);
  const [interim, setInterim] = useState("");
  const recoRef = useRef<SpeechRecognition | null>(null);
  const holdingRef = useRef(false);
  const finalsRef = useRef("");
  const interimRef = useRef("");
  const recorderRef = useRef<MediaRecorder | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);
  const recordingRef = useRef(false);
  const autoMicTimerRef = useRef<number | null>(null);

  useEffect(() => {
    recordingRef.current = recording;
  }, [recording]);

  const Ctor = useMemo(() => getSpeechCtor(), []);

  useEffect(() => {
    setSupported(Boolean(Ctor));
  }, [Ctor]);

  useEffect(() => {
    const ok =
      typeof window !== "undefined" &&
      typeof MediaRecorder !== "undefined" &&
      (MediaRecorder.isTypeSupported("audio/webm") ||
        MediaRecorder.isTypeSupported("audio/webm;codecs=opus") ||
        MediaRecorder.isTypeSupported("audio/mp4"));
    setMrSupported(ok);
  }, []);

  const teardown = useCallback(() => {
    const r = recoRef.current;
    if (r) {
      try {
        r.stop();
      } catch {
        /* ignore */
      }
    }
    recoRef.current = null;
    props.onListeningChange?.(false);
    setInterim("");
    interimRef.current = "";
  }, [props]);

  const clearAutoMic = useCallback(() => {
    if (autoMicTimerRef.current != null) {
      window.clearTimeout(autoMicTimerRef.current);
      autoMicTimerRef.current = null;
    }
  }, []);

  const finalizeSpokenText = useCallback(
    (raw: string) => {
      let t = raw.replace(/\s+/g, " ").trim();
      if (wakeStripFriday) t = stripFridayWakePrefix(t);
      props.onFinalText(t);
    },
    [props, wakeStripFriday],
  );

  const flushUtterance = useCallback(() => {
    const text = `${finalsRef.current} ${interimRef.current}`.replace(/\s+/g, " ").trim();
    finalsRef.current = "";
    interimRef.current = "";
    setInterim("");
    const applied = wakeStripFriday ? stripFridayWakePrefix(text) : text.trim();
    if (applied) props.onFinalText(applied);
  }, [props, wakeStripFriday]);

  const bindReco = useCallback(() => {
    if (!Ctor) return null;
    const r = new Ctor();
    r.lang = typeof navigator !== "undefined" ? navigator.language || "en-US" : "en-US";
    r.interimResults = true;
    r.maxAlternatives = 1;
    r.continuous = true;
    r.onresult = (ev: SpeechRecognitionEvent) => {
      let interimText = "";
      for (let i = ev.resultIndex; i < ev.results.length; i++) {
        const res = ev.results.item(i);
        const chunk = res.item(0).transcript;
        if (res.isFinal) {
          finalsRef.current += chunk;
        } else {
          interimText += chunk;
        }
      }
      interimRef.current = interimText;
      setInterim(interimText.trim());
    };
    r.onerror = () => teardown();
    r.onend = () => {
      if (!holdingRef.current) teardown();
    };
    return r;
  }, [Ctor, teardown]);

  const startReco = useCallback(() => {
    if (!Ctor || props.disabled || !supported) return;
    finalsRef.current = "";
    interimRef.current = "";
    setInterim("");
    teardown();
    const r = bindReco();
    if (!r) return;
    recoRef.current = r;
    r.start();
    props.onListeningChange?.(true);
  }, [Ctor, bindReco, props, supported, teardown]);

  const stopServerRecording = useCallback(async () => {
    const mr = recorderRef.current;
    if (!mr || mr.state === "inactive") {
      recorderRef.current = null;
      setRecording(false);
      mediaStreamRef.current?.getTracks().forEach((t) => {
        try {
          t.stop();
        } catch {
          /* ignore */
        }
      });
      mediaStreamRef.current = null;
      return;
    }
    const blobMime = mr.mimeType && mr.mimeType.length ? mr.mimeType : "audio/webm";
    const partsSnapshot = [...chunksRef.current];
    await new Promise<void>((resolve) => {
      mr.onstop = () => resolve();
      mr.stop();
    });
    recorderRef.current = null;
    setRecording(false);
    chunksRef.current = [];
    mediaStreamRef.current?.getTracks().forEach((t) => {
      try {
        t.stop();
      } catch {
        /* ignore */
      }
    });
    mediaStreamRef.current = null;

    const blob = new Blob(partsSnapshot, { type: blobMime });
    props.onListeningChange?.(false);
    if (!props.transcribeUploader) return;
    try {
      const text = await props.transcribeUploader(blob);
      if (text.trim()) finalizeSpokenText(text);
    } catch {
      /* parent may toast */
    }
  }, [finalizeSpokenText, props]);

  const startServerRecording = useCallback(async () => {
    if (!props.connected || !props.transcribeUploader || props.disabled || !mrSupported) return;
    if (recordingRef.current) return;
    teardown();
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true }).catch(() => null);
    if (!stream) return;
    mediaStreamRef.current = stream;
    let mimeOpt: string | undefined;
    if (MediaRecorder.isTypeSupported("audio/webm;codecs=opus")) mimeOpt = "audio/webm;codecs=opus";
    else if (MediaRecorder.isTypeSupported("audio/webm")) mimeOpt = "audio/webm";
    else if (MediaRecorder.isTypeSupported("audio/mp4")) mimeOpt = "audio/mp4";

    chunksRef.current = [];
    const mr = new MediaRecorder(stream, mimeOpt ? { mimeType: mimeOpt } : undefined);
    recorderRef.current = mr;
    mr.ondataavailable = (ev: BlobEvent) => {
      if (ev.data && ev.data.size) chunksRef.current.push(ev.data);
    };
    mr.start(220);
    setRecording(true);
    props.onListeningChange?.(true);
  }, [mrSupported, props, teardown]);

  const onHoldStart = useCallback(() => {
    if (!props.connected) return;
    clearAutoMic();
    if (sttMode === "server") void startServerRecording();
    else {
      holdingRef.current = true;
      startReco();
    }
  }, [clearAutoMic, props.connected, startReco, startServerRecording, sttMode]);

  const onHoldEnd = useCallback(() => {
    clearAutoMic();
    if (sttMode === "server") void stopServerRecording();
    else {
      holdingRef.current = false;
      const r = recoRef.current;
      if (r) {
        try {
          r.stop();
        } catch {
          /* ignore */
        }
      }
      window.setTimeout(() => {
        flushUtterance();
        teardown();
      }, 160);
    }
  }, [clearAutoMic, flushUtterance, sttMode, stopServerRecording, teardown]);

  const beginAutoMicWindow = useCallback(
    (ms: number) => {
      if (!props.connected || props.disabled || sttMode === "server" || !supported) return;
      clearAutoMic();
      holdingRef.current = true;
      startReco();
      autoMicTimerRef.current = window.setTimeout(() => {
        onHoldEnd();
      }, ms);
    },
    [clearAutoMic, onHoldEnd, props.connected, props.disabled, startReco, sttMode, supported],
  );

  useImperativeHandle(
    ref,
    () => ({
      kickAfterAssistantSpeak: () => beginAutoMicWindow(12000),
    }),
    [beginAutoMicWindow],
  );

  const serverBusy = recording;
  const baseDisabled = props.disabled || !props.connected;
  const micDisabled =
    sttMode === "server"
      ? !mrSupported || !props.transcribeUploader
      : supported !== true;

  return (
    <div className="space-y-2 rounded-xl border border-white/10 bg-gradient-to-r from-emerald-950/50 to-black/40 px-3 py-3">
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          disabled={baseDisabled || (serverBusy ? false : micDisabled)}
          onPointerDown={onHoldStart}
          onPointerUp={() => {
            if (sttMode === "server") void stopServerRecording();
            else onHoldEnd();
          }}
          onPointerLeave={() => {
            if (sttMode === "browser") onHoldEnd();
          }}
          className="select-none rounded-full bg-emerald-600 px-4 py-2 text-xs font-semibold uppercase tracking-wide text-white shadow-lg shadow-emerald-600/30 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {sttMode === "server"
            ? serverBusy
              ? "Recording… tap to stop"
              : "Hold to speak (server)"
            : "Hold to speak"}
        </button>
        <span className="text-xs text-zinc-400">
          {sttMode === "server"
            ? "MediaRecorder uploads to Whisper-compatible STT."
            : "Streaming transcription via Web Speech API · optional “Friday…” wake strip."}
        </span>
      </div>
      {!props.connected ? (
        <p className="text-[11px] text-amber-200/90">Connect realtime for push-to-talk (STT routing hints).</p>
      ) : null}
      {sttMode === "browser" && supported === false ? (
        <p className="text-[11px] text-rose-200/90">Speech recognition unsupported in this browser. Use server STT or type instead.</p>
      ) : null}
      {sttMode === "server" && !mrSupported ? (
        <p className="text-[11px] text-rose-200/90">
          Browser cannot record MediaRecorder webm-style audio here. Fallback to browser STT.
        </p>
      ) : null}
      {sttMode === "browser" && interim ? (
        <p className="rounded-md bg-black/50 px-2 py-1 font-mono text-[12px] text-emerald-200/90">{interim}</p>
      ) : (
        <p className="text-[11px] text-zinc-500">Duplex-lite: after replies, optionally auto-open a timed mic window.</p>
      )}
    </div>
  );
});
