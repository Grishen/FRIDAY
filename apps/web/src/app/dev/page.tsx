"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { apiBase } from "@/lib/config";

type Meta = {
  service: string;
  version: string;
  environment: string;
  build_id: string | null;
  urls: { openapi_json: string; swagger_ui: string; redoc: string };
};

type Ready = {
  status: string;
  database: boolean;
  redis: boolean;
  database_error: string | null;
  redis_error: string | null;
};

export default function DevPlatformPage() {
  const origin = apiBase.replace(/\/$/, "");
  const docsUrl = `${origin}/docs`;
  const openapiUrl = `${origin}/openapi.json`;
  const redocUrl = `${origin}/redoc`;

  const [meta, setMeta] = useState<Meta | null>(null);
  const [ready, setReady] = useState<Ready | null>(null);
  const [metaErr, setMetaErr] = useState<string | null>(null);
  const [readyErr, setReadyErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    setMetaErr(null);
    setReadyErr(null);
    try {
      const m = await fetch(`${origin}/api/v1/meta`);
      if (!m.ok) throw new Error(`${m.status} meta`);
      setMeta((await m.json()) as Meta);
    } catch (e) {
      setMetaErr(String(e));
      setMeta(null);
    }
    try {
      const r = await fetch(`${origin}/api/v1/ready`);
      const body = (await r.json()) as Ready;
      setReady(body);
    } catch (e) {
      setReadyErr(String(e));
      setReady(null);
    }
  }, [origin]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="mx-auto max-w-5xl px-6 py-16 text-zinc-100">
      <p className="text-xs uppercase tracking-[0.24em] text-emerald-400">Phase 9 · Developer platform</p>
      <h1 className="mt-3 text-3xl font-semibold">Introspection and tooling</h1>
      <p className="mt-4 max-w-2xl text-zinc-400">
        Runtime readiness checks, package metadata, and links to FastAPI docs. No auth headers required for these GETs.
      </p>
      <div className="mt-8 flex flex-wrap gap-4 text-sm">
        <button
          type="button"
          onClick={() => void load()}
          className="rounded-md border border-white/15 bg-white/5 px-4 py-2 text-white hover:bg-white/10"
        >
          Refresh probes
        </button>
        <Link className="rounded-md border border-emerald-500/40 px-4 py-2 text-emerald-300 hover:bg-emerald-500/10" href="/debug">
          Audit debug →
        </Link>
      </div>

      <section className="mt-12 grid gap-8 lg:grid-cols-2">
        <div className="rounded-xl border border-white/10 bg-zinc-950/60 p-5">
          <h2 className="text-lg font-semibold text-white">Live readiness</h2>
          {readyErr ? (
            <p className="mt-3 text-sm text-rose-300">{readyErr}</p>
          ) : ready ? (
            <ul className="mt-4 space-y-3 text-sm text-zinc-300">
              <li className="flex items-center gap-2">
                <Dot ok={ready.database} />
                Postgres <span className="font-mono text-[11px] text-zinc-500">(sessions, tools)</span>
              </li>
              {ready.database_error ? (
                <li className="text-xs text-rose-200/90">{ready.database_error}</li>
              ) : null}
              <li className="flex items-center gap-2">
                <Dot ok={ready.redis} />
                Redis <span className="font-mono text-[11px] text-zinc-500">(cache · Celery broker)</span>
              </li>
              {ready.redis_error ? (
                <li className="text-xs text-amber-200/90">{ready.redis_error}</li>
              ) : null}
              <li className="border-t border-white/5 pt-3 text-emerald-200/90">
                status: <strong className="text-white">{ready.status}</strong>
              </li>
            </ul>
          ) : (
            <p className="mt-4 text-zinc-500">Loading…</p>
          )}
        </div>

        <div className="rounded-xl border border-white/10 bg-zinc-950/60 p-5">
          <h2 className="text-lg font-semibold text-white">Build meta</h2>
          {metaErr ? (
            <p className="mt-3 text-sm text-rose-300">{metaErr}</p>
          ) : meta ? (
            <dl className="mt-4 space-y-2 font-mono text-xs text-zinc-400">
              <div>
                <dt className="text-zinc-600">service</dt>
                <dd className="text-emerald-300">{meta.service}</dd>
              </div>
              <div>
                <dt className="text-zinc-600">version</dt>
                <dd>{meta.version}</dd>
              </div>
              <div>
                <dt className="text-zinc-600">environment</dt>
                <dd>{meta.environment}</dd>
              </div>
              <div>
                <dt className="text-zinc-600">build_id</dt>
                <dd>{meta.build_id ?? "— (set FRIDAY_BUILD_ID / GIT_COMMIT_SHA)"}</dd>
              </div>
              <div className="border-t border-white/10 pt-3">
                <p className="text-zinc-500">API explorer</p>
                <div className="mt-2 flex flex-col gap-1">
                  <a className="text-emerald-400 hover:underline" href={docsUrl} target="_blank" rel="noopener noreferrer">
                    Swagger UI (/docs)
                  </a>
                  <a className="text-emerald-400 hover:underline" href={openapiUrl} target="_blank" rel="noopener noreferrer">
                    OpenAPI JSON (/openapi.json)
                  </a>
                  <a className="text-emerald-400 hover:underline" href={redocUrl} target="_blank" rel="noopener noreferrer">
                    ReDoc (/redoc)
                  </a>
                </div>
              </div>
            </dl>
          ) : (
            <p className="mt-4 text-zinc-500">Loading…</p>
          )}
        </div>
      </section>
    </div>
  );
}

function Dot({ ok }: { ok: boolean }) {
  return (
    <span
      className={`inline-block h-2.5 w-2.5 shrink-0 rounded-full ${ok ? "bg-emerald-400 shadow-[0_0_12px_rgba(52,211,153,0.6)]" : "bg-rose-500"}`}
      title={ok ? "ok" : "down"}
      aria-hidden
    />
  );
}
