"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { apiBase } from "@/lib/config";
import { useFridayStore } from "@/store/friday";

type DocRow = {
  id: string;
  title: string;
  status: string;
  chunk_count: number;
  created_at: string;
};

type QResponse = {
  answer: string;
  citations: {
    document_title: string;
    chunk_ordinal: number;
    score: number;
    excerpt: string;
  }[];
};

export function DocumentsConsole() {
  const userId = useFridayStore((s) => s.userId);
  const [items, setItems] = useState<DocRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [q, setQ] = useState("");
  const [rag, setRag] = useState<QResponse | null>(null);

  const load = useCallback(async () => {
    if (!userId) return;
    setLoading(true);
    setError(null);
    try {
      const res = (await apiFetch("/api/v1/documents", { userId })) as { items: DocRow[] };
      setItems(res.items ?? []);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [userId]);

  useEffect(() => {
    void load();
  }, [load]);

  const upload = async () => {
    if (!userId || !file) return;
    setError(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      if (title.trim()) {
        fd.append("title", title.trim());
      }
      const res = await fetch(`${apiBase}/api/v1/documents/upload`, {
        method: "POST",
        headers: { "X-User-Id": userId },
        body: fd,
      });
      if (!res.ok) {
        const t = await res.text();
        throw new Error(`${res.status} ${t}`);
      }
      await load();
      setFile(null);
      setTitle("");
    } catch (e) {
      setError(String(e));
    }
  };

  const runQuery = async () => {
    if (!userId || !q.trim()) return;
    setError(null);
    try {
      const res = (await apiFetch("/api/v1/documents/query", {
        method: "POST",
        userId,
        body: JSON.stringify({ query: q.trim(), limit: 10 }),
      })) as QResponse;
      setRag(res);
    } catch (e) {
      setError(String(e));
    }
  };

  if (!userId) {
    return <p className="text-sm text-zinc-500">Open the assistant first to bootstrap identity.</p>;
  }

  return (
    <div className="space-y-10 text-zinc-100">
      {error ? (
        <p className="rounded-lg border border-rose-500/40 bg-rose-950/40 px-4 py-2 text-sm text-rose-100">
          {error}
        </p>
      ) : null}

      <section className="rounded-2xl border border-white/10 bg-zinc-950/60 p-6">
        <h2 className="text-lg font-semibold text-white">Upload UTF-8 text</h2>
        <p className="mt-2 text-sm text-zinc-400">
          Files are chunked, embedded with the dev mock embedder, and stored in Postgres + pgvector. API:{" "}
          <span className="font-mono text-emerald-300">POST .../documents/upload</span>
        </p>
        <div className="mt-4 grid gap-3 md:grid-cols-2">
          <label className="text-xs text-zinc-400">
            Optional title override
            <input
              className="mt-1 w-full rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-sm"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Defaults to filename"
            />
          </label>
          <label className="text-xs text-zinc-400">
            .txt file
            <input
              type="file"
              accept=".txt,text/plain"
              className="mt-1 block w-full text-sm text-zinc-300 file:rounded-md file:border-0 file:bg-emerald-600 file:px-3 file:py-2 file:text-white"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </label>
        </div>
        <button
          type="button"
          disabled={!file}
          className="mt-4 rounded-xl bg-emerald-600 px-5 py-2 text-sm font-semibold text-white hover:bg-emerald-500 disabled:opacity-40"
          onClick={() => void upload()}
        >
          Ingest & embed
        </button>
      </section>

      <section className="rounded-2xl border border-white/10 bg-zinc-950/60 p-6">
        <h2 className="text-lg font-semibold text-white">Ask with citations</h2>
        <textarea
          className="mt-4 min-h-[80px] w-full rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-sm"
          placeholder="What do the uploads say about…?"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <button
          type="button"
          className="mt-3 rounded-xl bg-emerald-600 px-5 py-2 text-sm font-semibold text-white hover:bg-emerald-500"
          onClick={() => void runQuery()}
        >
          Query RAG
        </button>
        {rag ? (
          <div className="mt-6 space-y-4">
            <p className="whitespace-pre-wrap text-sm text-zinc-100">{rag.answer}</p>
            <ul className="space-y-2">
              {rag.citations.map((c, idx) => (
                <li key={idx} className="rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-xs">
                  <span className="font-mono text-emerald-400">
                    {(c.score * 100).toFixed(0)}%{" "}
                  </span>
                  {c.document_title} · chunk #{c.chunk_ordinal}
                  <p className="mt-1 text-zinc-400">{c.excerpt}</p>
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <p className="mt-4 text-sm text-zinc-500">Responses include scored chunk excerpts.</p>
        )}
      </section>

      <section>
        <h2 className="text-lg font-semibold text-white">Your documents ({items.length})</h2>
        {loading ? <p className="mt-4 text-sm text-zinc-500">Loading…</p> : null}
        <ul className="mt-4 space-y-2">
          {items.map((d) => (
            <li key={d.id} className="rounded-lg border border-white/10 bg-white/5 px-4 py-2 text-sm">
              <span className="font-medium text-white">{d.title}</span> · {d.chunk_count} chunks · {d.status}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
