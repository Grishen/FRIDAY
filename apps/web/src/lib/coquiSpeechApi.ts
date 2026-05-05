import { apiBase } from "./config";

export type WakePhraseScanResult = {
  text: string;
  triggered: boolean;
};

export async function postWakePhraseScan(blob: Blob, userId: string): Promise<WakePhraseScanResult> {
  const fd = new FormData();
  fd.append("file", blob, "wake.webm");
  const res = await fetch(`${apiBase}/api/v1/speech/coqui/wake-scan`, {
    method: "POST",
    headers: { "X-User-Id": userId },
    body: fd,
  });
  if (!res.ok) {
    const t = await res.text();
    throw new Error(`${res.status} ${t}`);
  }
  return (await res.json()) as WakePhraseScanResult;
}
