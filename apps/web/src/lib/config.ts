/**
 * `./scripts/run-api.sh` binds `127.0.0.1:8000`. If `NEXT_PUBLIC_API_URL` still uses `localhost`,
 * some systems resolve `localhost` → IPv6 (::1) first → connection refused vs IPv4-only server.
 *
 * Normalize at runtime so old `.env.local` entries keep working.
 */
export function normalizeLocalApiOrigin(raw: string): string {
  const fallback = "http://127.0.0.1:8000";
  const trimmed = raw.trim();
  if (!trimmed) return fallback;
  try {
    const withScheme = /^https?:\/\//i.test(trimmed) ? trimmed : `http://${trimmed}`;
    const u = new URL(withScheme);
    if (u.hostname === "localhost") {
      u.hostname = "127.0.0.1";
    }
    return u.origin;
  } catch {
    return fallback;
  }
}

const fromEnv =
  typeof process.env.NEXT_PUBLIC_API_URL === "string"
    ? process.env.NEXT_PUBLIC_API_URL.trim()
    : "";

export const apiBase = normalizeLocalApiOrigin(fromEnv || "http://127.0.0.1:8000");
