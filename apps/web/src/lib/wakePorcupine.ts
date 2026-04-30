import { BuiltInKeyword, PorcupineWorker } from "@picovoice/porcupine-web";
import { WebVoiceProcessor } from "@picovoice/web-voice-processor";

const MODEL_URL =
  typeof process.env.NEXT_PUBLIC_PICOVOICE_MODEL_URL === "string" &&
  process.env.NEXT_PUBLIC_PICOVOICE_MODEL_URL.trim().length > 0
    ? process.env.NEXT_PUBLIC_PICOVOICE_MODEL_URL.trim()
    : "https://raw.githubusercontent.com/Picovoice/porcupine/master/lib/common/porcupine_params.pv";

/** Resolve `"Jarvis"`, `"Hey Google"`, … to `BuiltInKeyword`. */
export function resolvePorcupineBuiltin(raw: string): BuiltInKeyword {
  const trimmed = raw.trim();

  const directHit = Object.values(BuiltInKeyword).find((v) => v === trimmed);
  if (directHit) return directHit;

  const viaKey = BuiltInKeyword[trimmed as keyof typeof BuiltInKeyword];
  if (viaKey !== undefined) return viaKey;

  throw new Error(
    `Unknown Porcupine built-in '${trimmed}'. See Picovoice BuiltInKeyword (e.g. Jarvis, Computer, Grasshopper).`,
  );
}

export async function armPorcupineWakeWordBuiltin(
  accessKey: string,
  builtinName: string,
  onDetect: () => void | Promise<void>,
): Promise<{ disarm: () => Promise<void> }> {
  const builtin = resolvePorcupineBuiltin(builtinName);

  await WebVoiceProcessor.reset().catch(() => undefined);

  let lastEmit = 0;
  const worker = await PorcupineWorker.create(
    accessKey,
    { builtin, sensitivity: 0.72 },
    () => {
      const now = Date.now();
      if (now - lastEmit < 2000) return;
      lastEmit = now;
      void Promise.resolve(onDetect()).catch(() => undefined);
    },
    { publicPath: MODEL_URL },
  );

  await WebVoiceProcessor.subscribe(worker);

  return {
    disarm: async (): Promise<void> => {
      await WebVoiceProcessor.unsubscribe(worker).catch(() => undefined);
      await worker.release().catch(() => undefined);
      await WebVoiceProcessor.reset().catch(() => undefined);
    },
  };
}
