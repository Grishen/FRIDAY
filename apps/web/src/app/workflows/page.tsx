"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { apiFetch } from "@/lib/api";
import { useFridayStore } from "@/store/friday";

type Template = { id: string; title: string; description: string; step_count: number };
type Step = { id: string; name: string; status: string; order: number };
type Wf = {
  id: string;
  template: string;
  state: string;
  context: Record<string, unknown> | null;
  steps: Step[];
};

export default function WorkflowsPage() {
  const { userId, setUserId } = useFridayStore();
  const [templates, setTemplates] = useState<Template[]>([]);
  const [workflows, setWorkflows] = useState<Wf[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const bootstrap = useCallback(async () => {
    const res = (await apiFetch("/api/v1/auth/bootstrap", {
      method: "POST",
      body: JSON.stringify({ email: "user@example.com" }),
    })) as { user_id: string };
    setUserId(res.user_id);
  }, [setUserId]);

  const load = useCallback(async () => {
    if (!userId) return;
    setError(null);
    const [t, w] = await Promise.all([
      apiFetch("/api/v1/workflows/templates", { userId }) as Promise<{ items: Template[] }>,
      apiFetch("/api/v1/workflows", { userId }) as Promise<{ items: Wf[] }>,
    ]);
    setTemplates(t.items);
    setWorkflows(w.items);
  }, [userId]);

  useEffect(() => {
    if (!userId) void bootstrap();
  }, [bootstrap, userId]);

  useEffect(() => {
    void load();
  }, [load]);

  const start = async (template: string) => {
    if (!userId) return;
    setBusy(true);
    setError(null);
    try {
      await apiFetch("/api/v1/workflows", {
        method: "POST",
        userId,
        body: JSON.stringify({ template }),
      });
      await load();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-5xl px-6 py-16 text-zinc-100">
      <p className="text-xs uppercase tracking-[0.24em] text-emerald-400">Workflows</p>
      <h1 className="mt-3 text-3xl font-semibold">Automation & playbooks</h1>
      <p className="mt-4 text-zinc-400">
        Deterministic runs: immediate steps execute first; high-risk tool steps pause until you approve in the
        assistant (same approval queue as chat).{" "}
        <Link className="text-emerald-400 hover:underline" href="/">
          Open chat
        </Link>
      </p>

      {error && (
        <p className="mt-6 rounded border border-red-900/60 bg-red-950/40 px-4 py-2 text-sm text-red-200">
          {error}
        </p>
      )}

      <section className="mt-10">
        <h2 className="text-sm font-medium text-zinc-300">Templates</h2>
        <ul className="mt-4 space-y-3">
          {templates.map((t) => (
            <li
              key={t.id}
              className="flex flex-col gap-2 rounded-lg border border-zinc-800 bg-zinc-950/50 px-4 py-3 sm:flex-row sm:items-center sm:justify-between"
            >
              <div>
                <p className="font-medium text-zinc-100">{t.title}</p>
                <p className="text-sm text-zinc-500">{t.description}</p>
                <p className="mt-1 text-xs text-zinc-600">{t.step_count} steps</p>
              </div>
              <button
                type="button"
                disabled={!userId || busy}
                onClick={() => void start(t.id)}
                className="shrink-0 rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500 disabled:opacity-40"
              >
                Start
              </button>
            </li>
          ))}
        </ul>
      </section>

      <section className="mt-12">
        <h2 className="text-sm font-medium text-zinc-300">Your runs</h2>
        {workflows.length === 0 ? (
          <p className="mt-4 text-sm text-zinc-500">No workflows yet — start a template above.</p>
        ) : (
          <ul className="mt-4 space-y-4">
            {workflows.map((wf) => {
              const pend =
                wf.context &&
                typeof wf.context.pending_approval_id === "string"
                  ? wf.context.pending_approval_id
                  : null;
              return (
              <li key={wf.id} className="rounded-lg border border-zinc-800 bg-zinc-950/50 px-4 py-3">
                <div className="flex flex-wrap items-baseline gap-2">
                  <span className="font-mono text-xs text-zinc-500">{wf.id.slice(0, 8)}…</span>
                  <span className="text-sm text-emerald-400/90">{wf.template}</span>
                  <span className="rounded bg-zinc-800 px-2 py-0.5 text-xs uppercase tracking-wide text-zinc-300">
                    {wf.state}
                  </span>
                </div>
                <ol className="mt-3 list-decimal pl-5 text-sm text-zinc-400">
                  {wf.steps
                    .slice()
                    .sort((a, b) => a.order - b.order)
                    .map((s) => (
                      <li key={s.id}>
                        <span className="text-zinc-200">{s.name}</span>{" "}
                        <span className="text-zinc-600">({s.status})</span>
                      </li>
                    ))}
                </ol>
                {pend ? (
                  <p className="mt-2 text-xs text-amber-200/90">
                    Pending approval — resolve in chat or via POST /approvals/{pend.slice(0, 8)}…/resolve
                  </p>
                ) : null}
              </li>
            );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}
