import { apiBase } from "./config";

type FetchOpts = RequestInit & { userId?: string };

export async function apiFetch(path: string, opts: FetchOpts = {}) {
  const { userId, headers: hdrs, ...rest } = opts;
  const headers = new Headers(hdrs);
  const isFormData = typeof FormData !== "undefined" && rest.body instanceof FormData;
  if (!isFormData) {
    headers.set("Content-Type", "application/json");
  }
  if (userId) {
    headers.set("X-User-Id", userId);
  }

  let res: Response;
  try {
    res = await fetch(`${apiBase}${path}`, {
      ...rest,
      headers,
    });
  } catch (e) {
    const msg =
      e instanceof Error
        ? e.message
        : typeof e === "string"
          ? e
          : "unknown network error";
    throw new Error(
      `${msg}: cannot fetch ${apiBase}${path}. Ensure the API is running (e.g. ./scripts/run-api.sh), ` +
        `NEXT_PUBLIC_API_URL matches the API URL (recommended http://127.0.0.1:8000), and FastAPI ` +
        `CORS_ORIGINS includes both http://localhost:3000 and http://127.0.0.1:3000 if you switch hosts.`,
    );
  }
  if (!res.ok) {
    const txt = await res.text();
    throw new Error(`${res.status} ${txt}`);
  }
  const text = await res.text();
  if (!text.trim()) {
    return null;
  }
  try {
    return JSON.parse(text) as unknown;
  } catch {
    throw new Error(`Invalid JSON response: ${text.slice(0, 120)}`);
  }
}
