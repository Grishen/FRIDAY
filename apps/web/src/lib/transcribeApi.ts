import { apiBase } from "./config";

export async function transcribeSessionAudio(sessionId: string, blob: Blob, userId: string): Promise<string> {
  const fd = new FormData();
  fd.append("file", blob, blob.type.includes("wav") ? "clip.wav" : "clip.webm");
  let res: Response;
  try {
    res = await fetch(`${apiBase}/api/v1/sessions/${sessionId}/transcribe`, {
      method: "POST",
      headers: { "X-User-Id": userId },
      body: fd,
    });
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    throw new Error(
      `${msg}: cannot transcribe via ${apiBase}. Ensure OPENAI_API_KEY is set server-side when not in pytest.`,
    );
  }
  if (!res.ok) {
    const txt = await res.text();
    throw new Error(`${res.status} ${txt}`);
  }
  const j = (await res.json()) as { text?: string };
  if (!j.text) throw new Error("empty transcription");
  return j.text.trim();
}
