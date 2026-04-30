import { apiBase } from "./config";

type SseHandlers = {
  onUserCommitted?: (id: string, content: string) => void;
  onDelta?: (text: string) => void;
  onAssistantFinal?: (content: string, meta: unknown) => void;
};

function parseSseBlocks(buffer: string): { events: Array<{ event: string; rawData: string }>; rest: string } {
  const parts = buffer.split("\n\n");
  const rest = parts.pop() ?? "";
  const events: Array<{ event: string; rawData: string }> = [];
  for (const block of parts) {
    const trimmed = block.trim();
    if (!trimmed) continue;
    let event = "message";
    const dataLines: string[] = [];
    for (const line of trimmed.split("\n")) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
    }
    if (!dataLines.length) continue;
    events.push({ event, rawData: dataLines.join("\n") });
  }
  return { events, rest };
}

/** POST `/sessions/:id/messages/stream` — consume SSE until `done`. */
export async function postSessionMessageStream(
  sessionId: string,
  content: string,
  userId: string,
  handlers: SseHandlers,
): Promise<void> {
  const res = await fetch(`${apiBase}/api/v1/sessions/${sessionId}/messages/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-User-Id": userId,
    },
    body: JSON.stringify({ content }),
  });
  if (!res.ok) {
    const txt = await res.text();
    throw new Error(`${res.status} ${txt}`);
  }
  const reader = res.body?.getReader();
  if (!reader) throw new Error("stream missing");

  const dec = new TextDecoder();
  let carry = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    carry += dec.decode(value, { stream: true }).replace(/\r/g, "");
    const { events, rest } = parseSseBlocks(carry);
    carry = rest;
    for (const ev of events) {
      let data: Record<string, unknown>;
      try {
        data = JSON.parse(ev.rawData) as Record<string, unknown>;
      } catch {
        continue;
      }
      if (ev.event === "conversation.user" && handlers.onUserCommitted) {
        const id = typeof data.id === "string" ? data.id : "";
        const c = typeof data.content === "string" ? data.content : "";
        if (id || c) handlers.onUserCommitted(id, c || content);
      }
      if (ev.event === "error") {
        throw new Error(String(data.detail ?? "stream_error"));
      }
      if (ev.event === "assistant.delta") {
        const t = typeof data.text === "string" ? data.text : "";
        if (t) handlers.onDelta?.(t);
      }
      if (ev.event === "assistant.message" && handlers.onAssistantFinal) {
        const c = typeof data.content === "string" ? data.content : "";
        handlers.onAssistantFinal(c, data.meta ?? null);
      }
    }
  }
}
