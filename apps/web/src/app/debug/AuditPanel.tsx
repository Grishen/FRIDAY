"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { useFridayStore } from "@/store/friday";

type AuditRow = {
  id: string;
  category: string;
  action: string;
  severity: string;
  created_at: string;
  payload: Record<string, unknown> | null;
};

export function AuditPanel() {
  const userId = useFridayStore((s) => s.userId);
  const [items, setItems] = useState<AuditRow[]>([]);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!userId) return;
    setErr(null);
    try {
      const res = (await apiFetch("/api/v1/audit", { userId })) as { items: AuditRow[] };
      setItems(res.items ?? []);
    } catch (e) {
      setErr(String(e));
    }
  }, [userId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!userId) {
    return <p className="text-sm text-zinc-500">Open the assistant page once to bootstrap identity.</p>;
  }

  return (
    <div className="mt-8 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-medium text-white">Audit log (last 50)</h2>
        <button
          type="button"
          className="rounded-md border border-white/15 px-3 py-1.5 text-xs text-zinc-200 hover:bg-white/5"
          onClick={() => void load()}
        >
          Refresh
        </button>
      </div>
      {err ? <p className="text-sm text-rose-300">{err}</p> : null}
      <ul className="space-y-2">
        {items.length === 0 ? (
          <li className="text-sm text-zinc-500">No rows yet — approve or deny a tool to create entries.</li>
        ) : (
          items.map((row) => (
            <li key={row.id} className="rounded-lg border border-white/10 bg-zinc-950/60 p-3 font-mono text-[11px] text-zinc-300">
              <span className="text-emerald-400">{row.created_at}</span> · {row.category}.{row.action} ·{" "}
              {row.severity}
              {row.payload ? (
                <pre className="mt-2 max-h-32 overflow-auto whitespace-pre-wrap text-zinc-500">
                  {JSON.stringify(row.payload, null, 2)}
                </pre>
              ) : null}
            </li>
          ))
        )}
      </ul>
    </div>
  );
}
