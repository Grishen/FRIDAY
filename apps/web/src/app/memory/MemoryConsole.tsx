"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { useFridayStore } from "@/store/friday";

type MemoryRow = {
  id: string;
  memory_type: string;
  content: string;
  importance_score: number;
  sensitivity_level: string;
  has_embedding: boolean;
  created_at: string;
};

type SearchHit = {
  memory: MemoryRow;
  score: number;
};

export function MemoryConsole() {
  const userId = useFridayStore((s) => s.userId);
  const [items, setItems] = useState<MemoryRow[]>([]);
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [form, setForm] = useState({
    memory_type: "semantic",
    content: "",
    sensitivity_level: "internal",
    importance_score: 0.5,
  });
  const [search, setSearch] = useState("");
  const [searchKind, setSearchKind] = useState<"all" | string>("all");

  const load = useCallback(async () => {
    if (!userId) return;
    setLoading(true);
    setError(null);
    try {
      const res = (await apiFetch("/api/v1/memory", { userId })) as { items: MemoryRow[] };
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

  const create = async () => {
    if (!userId || !form.content.trim()) return;
    setError(null);
    try {
      await apiFetch("/api/v1/memory", {
        method: "POST",
        userId,
        body: JSON.stringify({
          memory_type: form.memory_type,
          content: form.content.trim(),
          sensitivity_level: form.sensitivity_level,
          importance_score: form.importance_score,
        }),
      });
      setForm((f) => ({ ...f, content: "" }));
      await load();
    } catch (e) {
      setError(String(e));
    }
  };

  const doSearch = async () => {
    if (!userId || !search.trim()) return;
    setError(null);
    try {
      const body: { query: string; limit: number; memory_type?: string } = {
        query: search.trim(),
        limit: 20,
      };
      if (searchKind !== "all") {
        body.memory_type = searchKind;
      }
      const res = (await apiFetch("/api/v1/memory/search", {
        method: "POST",
        userId,
        body: JSON.stringify(body),
      })) as { hits: SearchHit[] };
      setHits(res.hits ?? []);
    } catch (e) {
      setError(String(e));
    }
  };

  const remove = async (id: string) => {
    if (!userId) return;
    if (!window.confirm("Delete this memory?")) return;
    try {
      await apiFetch(`/api/v1/memory/${id}`, { method: "DELETE", userId });
      setHits(null);
      await load();
    } catch (e) {
      setError(String(e));
    }
  };

  if (!userId) {
    return <p className="text-sm text-zinc-500">Open the home console first to bootstrap identity.</p>;
  }

  return (
    <div className="space-y-10 text-zinc-100">
      {error ? (
        <p className="rounded-lg border border-rose-500/40 bg-rose-950/40 px-4 py-2 text-sm text-rose-100">
          {error}
        </p>
      ) : null}

      <section className="rounded-2xl border border-white/10 bg-zinc-950/60 p-6">
        <h2 className="text-lg font-semibold text-white">Vector search</h2>
        <p className="mt-2 text-sm text-zinc-400">
          Mock embeddings + cosine ranking (deterministic). Postgres pgvector-backed rows; SQL-side ANN tuning later.
        </p>
        <div className="mt-4 flex flex-wrap flex-col gap-3 sm:flex-row sm:items-end">
          <label className="text-xs text-zinc-400">
            Scope
            <select
              className="mt-1 block w-full min-w-[140px] rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-sm text-white sm:w-auto"
              value={searchKind}
              onChange={(e) => setSearchKind(e.target.value)}
            >
              <option value="all">All types</option>
              {["profile", "episodic", "semantic", "task"].map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </label>
          <input
            className="min-w-[240px] flex-1 rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-sm"
            placeholder="Search memories…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <button
            type="button"
            className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500"
            onClick={() => void doSearch()}
          >
            Search
          </button>
        </div>
        {hits ? (
          <ul className="mt-6 space-y-3">
            {hits.length === 0 ? (
              <li className="text-sm text-zinc-500">No scored hits.</li>
            ) : (
              hits.map((h) => (
                <li
                  key={h.memory.id}
                  className="rounded-lg border border-white/10 bg-black/40 px-4 py-3 text-sm"
                >
                  <div className="flex justify-between gap-4">
                    <span className="text-[11px] uppercase tracking-wide text-emerald-300">
                      {h.memory.memory_type} · {(h.score * 100).toFixed(1)}% match
                    </span>
                    <button type="button" className="text-xs text-rose-300 hover:underline" onClick={() => void remove(h.memory.id)}>
                      Delete
                    </button>
                  </div>
                  <p className="mt-2 whitespace-pre-wrap text-zinc-200">{h.memory.content}</p>
                </li>
              ))
            )}
          </ul>
        ) : (
          <p className="mt-4 text-sm text-zinc-500">Run a query to rank stored memories.</p>
        )}
      </section>

      <section className="rounded-2xl border border-white/10 bg-zinc-950/60 p-6">
        <h2 className="text-lg font-semibold text-white">Add memory</h2>
        <div className="mt-4 grid gap-4 md:grid-cols-2">
          <label className="text-xs text-zinc-400">
            Type
            <select
              className="mt-1 w-full rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-sm text-white"
              value={form.memory_type}
              onChange={(e) => setForm((f) => ({ ...f, memory_type: e.target.value }))}
            >
              {["profile", "episodic", "semantic", "task"].map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs text-zinc-400">
            Sensitivity
            <select
              className="mt-1 w-full rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-sm text-white"
              value={form.sensitivity_level}
              onChange={(e) => setForm((f) => ({ ...f, sensitivity_level: e.target.value }))}
            >
              {["public", "internal", "confidential", "restricted"].map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs text-zinc-400 md:col-span-2">
            Importance (0–1)
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              className="mt-2 block w-full accent-emerald-500"
              value={form.importance_score}
              onChange={(e) =>
                setForm((f) => ({ ...f, importance_score: Number.parseFloat(e.target.value) }))
              }
            />
            <span className="mt-1 block font-mono text-[11px] text-zinc-500">
              {form.importance_score.toFixed(2)}
            </span>
          </label>
        </div>
        <textarea
          className="mt-4 min-h-[100px] w-full rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-sm"
          placeholder="Durable fact you want FRIDAY to recall…"
          value={form.content}
          onChange={(e) => setForm((f) => ({ ...f, content: e.target.value }))}
        />
        <button
          type="button"
          className="mt-4 rounded-xl bg-emerald-600 px-5 py-2 text-sm font-semibold text-white hover:bg-emerald-500"
          onClick={() => void create()}
        >
          Save & embed
        </button>
      </section>

      <section>
        <h2 className="text-lg font-semibold text-white">All memories ({items.length})</h2>
        {loading ? <p className="mt-4 text-sm text-zinc-500">Loading…</p> : null}
        <ul className="mt-4 space-y-3">
          {items.map((m) => (
            <li key={m.id} className="rounded-lg border border-white/10 bg-white/5 px-4 py-3 text-sm">
              <div className="flex justify-between gap-4">
                <span className="text-[11px] uppercase tracking-wide text-emerald-300">
                  {m.memory_type}
                  {m.has_embedding ? " · embedded" : ""}
                  {" · "}
                  importance {Number(m.importance_score).toFixed(2)}
                </span>
                <button type="button" className="text-xs text-rose-300 hover:underline" onClick={() => void remove(m.id)}>
                  Delete
                </button>
              </div>
              <p className="mt-2 whitespace-pre-wrap text-zinc-200">{m.content}</p>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
