/** Browser + optional Coqui Studio XTTS playback for assistant replies. */

import { chunkXttsEnglish } from "./coquiTextChunks";
import { apiBase } from "./config";

export type SpeakFridayOpts = {
  userId?: string | null;
  onEnd?: () => void;
};

let coquiAbort: AbortController | null = null;

function coquiTtsEnabledFromEnv(): boolean {
  return typeof process !== "undefined" && process.env.NEXT_PUBLIC_USE_COQUI_TTS === "1";
}

async function fetchCoquiWav(text: string, userId: string, signal: AbortSignal): Promise<ArrayBuffer> {
  const res = await fetch(`${apiBase}/api/v1/speech/coqui/tts`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-User-Id": userId,
    },
    signal,
    body: JSON.stringify({ text }),
  });
  if (!res.ok) {
    throw new Error(`coqui_tts:${res.status} ${await res.text()}`);
  }
  return res.arrayBuffer();
}

async function playSequentialWavs(buffers: ArrayBuffer[], onEnd?: () => void): Promise<void> {
  type CtxCtor = typeof AudioContext;
  const Ctor =
    typeof window !== "undefined"
      ? (window.AudioContext ?? (window as unknown as { webkitAudioContext?: CtxCtor }).webkitAudioContext)
      : undefined;
  if (!Ctor) {
    onEnd?.();
    return;
  }
  const ctx = new Ctor();
  try {
    for (const raw of buffers) {
      const copy = raw.slice(0);
      const audioBuf = await ctx.decodeAudioData(copy);
      await new Promise<void>((resolve, reject) => {
        const src = ctx.createBufferSource();
        src.buffer = audioBuf;
        src.connect(ctx.destination);
        src.onended = () => resolve();
        try {
          src.start(0);
        } catch (e) {
          reject(e);
        }
      });
    }
    onEnd?.();
  } finally {
    await ctx.close().catch(() => undefined);
  }
}

async function speakCoqui(text: string, userId: string, onEnd?: () => void): Promise<void> {
  const clean = text.replace(/\s+/g, " ").trim();
  if (!clean) {
    onEnd?.();
    return;
  }
  coquiAbort?.abort();
  coquiAbort = new AbortController();
  const signal = coquiAbort.signal;
  try {
    const wavs: ArrayBuffer[] = [];
    for (const frag of chunkXttsEnglish(clean)) {
      if (signal.aborted) return;
      wavs.push(await fetchCoquiWav(frag, userId, signal));
    }
    if (signal.aborted) return;
    await playSequentialWavs(wavs, onEnd);
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") return;
    if (typeof console !== "undefined" && typeof console.warn === "function") {
      console.warn("[fridayTts] coqui_failed_falling_back", e);
    }
    speakWebSpeech(clean, onEnd);
  } finally {
    if (coquiAbort?.signal === signal) coquiAbort = null;
  }
}

function speakWebSpeech(text: string, onEnd?: () => void): void {
  if (typeof window === "undefined" || !window.speechSynthesis) {
    onEnd?.();
    return;
  }
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.rate = 1;
  u.pitch = 1;
  if (onEnd) {
    u.onend = () => {
      window.setTimeout(() => onEnd(), 0);
    };
  }
  window.speechSynthesis.speak(u);
}

/**
 * Speaks assistant text. With `NEXT_PUBLIC_USE_COQUI_TTS=1` and a `userId`, calls the API
 * Coqui XTTS proxy and falls back to Web Speech API on failure.
 */
export function speakFriday(text: string, opts?: SpeakFridayOpts): void {
  const { userId = null, onEnd } = opts ?? {};
  if (coquiTtsEnabledFromEnv() && userId) {
    void speakCoqui(text, userId, onEnd);
    return;
  }
  const clean = text.replace(/\s+/g, " ").trim();
  if (!clean) return;
  speakWebSpeech(clean, onEnd);
}

export function stopFridaySpeech(): void {
  coquiAbort?.abort();
  coquiAbort = null;
  if (typeof window === "undefined" || !window.speechSynthesis) return;
  window.speechSynthesis.cancel();
}
