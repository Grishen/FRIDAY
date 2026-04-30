"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { apiFetch } from "@/lib/api";
import { useFridayStore } from "@/store/friday";

type NotifRow = {
  id: string;
  channel: string;
  title: string;
  body: string;
  payload: Record<string, unknown> | null;
  acknowledged: boolean;
  created_at: string;
};

type RuleRow = {
  id: string;
  title: string;
  rule_type: string;
  interval_minutes: number;
  enabled: boolean;
  last_fired_at: string | null;
  created_at: string;
};

type DispatchStats = {
  status: string;
  notifications_created: number;
  rules_evaluated: number;
};

export default function NotificationsPage() {
  const { userId, setUserId } = useFridayStore();
  const [notifications, setNotifications] = useState<NotifRow[]>([]);
  const [rules, setRules] = useState<RuleRow[]>([]);
  const [onlyUnacked, setOnlyUnacked] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [dispatchResult, setDispatchResult] = useState<DispatchStats | null>(null);
  /** Local draft interval keyed by rule id (minutes). */
  const [intervalDraft, setIntervalDraft] = useState<Record<string, string>>({});

  const bootstrap = useCallback(async () => {
    const res = (await apiFetch("/api/v1/auth/bootstrap", {
      method: "POST",
      body: JSON.stringify({ email: "notifications@example.com" }),
    })) as { user_id: string };
    setUserId(res.user_id);
  }, [setUserId]);

  const load = useCallback(async () => {
    if (!userId) return;
    setError(null);
    const q = onlyUnacked ? "?unacked_only=true" : "";
    const [n, r] = await Promise.all([
      apiFetch(`/api/v1/notifications${q}`, { userId }) as Promise<{ items: NotifRow[] }>,
      apiFetch("/api/v1/notifications/rules", { userId }) as Promise<{ items: RuleRow[] }>,
    ]);
    setNotifications(n.items);
    setRules(r.items);
    setIntervalDraft((prev) => {
      const next = { ...prev };
      for (const rule of r.items) {
        if (next[rule.id] === undefined) {
          next[rule.id] = String(rule.interval_minutes);
        }
      }
      return next;
    });
  }, [userId, onlyUnacked]);

  useEffect(() => {
    if (!userId) void bootstrap();
  }, [bootstrap, userId]);

  useEffect(() => {
    void load();
  }, [load]);

  const acknowledge = async (id: string) => {
    if (!userId) return;
    setBusy(true);
    setError(null);
    try {
      await apiFetch(`/api/v1/notifications/${id}/ack`, { method: "POST", userId });
      await load();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const runDispatch = async () => {
    if (!userId) return;
    setBusy(true);
    setError(null);
    try {
      const stats = (await apiFetch("/api/v1/notifications/dispatch", {
        method: "POST",
        userId,
      })) as DispatchStats;
      setDispatchResult(stats);
      await load();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const patchRule = async (ruleId: string, patch: { enabled?: boolean; interval_minutes?: number }) => {
    if (!userId) return;
    setBusy(true);
    setError(null);
    try {
      await apiFetch(`/api/v1/notifications/rules/${ruleId}`, {
        method: "PATCH",
        userId,
        body: JSON.stringify(patch),
      });
      await load();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const applyInterval = async (ruleId: string) => {
    const raw = intervalDraft[ruleId];
    const mins = Number.parseInt(raw ?? "", 10);
    if (Number.isNaN(mins) || mins < 5 || mins > 10080) {
      setError("Interval must be between 5 and 10080 minutes.");
      return;
    }
    await patchRule(ruleId, { interval_minutes: mins });
  };

  const toggleRule = async (rule: RuleRow) => void patchRule(rule.id, { enabled: !rule.enabled });

  return (
    <div className="mx-auto max-w-5xl px-6 py-16 text-zinc-100">
      <p className="text-xs uppercase tracking-[0.24em] text-emerald-400">Notifications</p>
      <h1 className="mt-3 text-3xl font-semibold">In-app inbox & proactive schedules</h1>
      <p className="mt-4 text-zinc-400">
        Rules drive timed in-app reminders (Celery beat runs every 5 minutes; you can also run a tick manually).
        Acknowledge items when you&apos;ve handled them.{" "}
        <Link className="text-emerald-400 hover:underline" href="/">
          Back to assistant
        </Link>
      </p>

      {error && (
        <p className="mt-6 rounded border border-red-900/60 bg-red-950/40 px-4 py-2 text-sm text-red-200">{error}</p>
      )}

      <section className="mt-10 flex flex-wrap items-center gap-4 border-b border-zinc-800 pb-6">
        <label className="flex cursor-pointer items-center gap-2 text-sm text-zinc-300">
          <input
            type="checkbox"
            className="rounded border-zinc-600 bg-zinc-900"
            checked={onlyUnacked}
            onChange={(e) => setOnlyUnacked(e.target.checked)}
          />
          Unread only
        </label>
        <button
          type="button"
          disabled={!userId || busy}
          onClick={() => void load()}
          className="rounded-md border border-zinc-700 px-4 py-2 text-sm text-zinc-200 hover:bg-zinc-900 disabled:opacity-40"
        >
          Refresh
        </button>
        <button
          type="button"
          disabled={!userId || busy}
          onClick={() => void runDispatch()}
          className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500 disabled:opacity-40"
        >
          Run dispatch now
        </button>
        {dispatchResult ? (
          <p className="text-sm text-zinc-500">
            Last tick: created {dispatchResult.notifications_created}, evaluated {dispatchResult.rules_evaluated}{" "}
            rule(s)
          </p>
        ) : null}
      </section>

      <section className="mt-10">
        <h2 className="text-sm font-medium text-zinc-300">Inbox</h2>
        {notifications.length === 0 ? (
          <p className="mt-4 text-sm text-zinc-500">No notifications — open rules below or run dispatch.</p>
        ) : (
          <ul className="mt-4 space-y-3">
            {notifications.map((n) => (
              <li
                key={n.id}
                className="flex flex-col gap-3 rounded-lg border border-zinc-800 bg-zinc-950/50 px-4 py-3 sm:flex-row sm:items-start sm:justify-between"
              >
                <div>
                  <div className="flex flex-wrap items-baseline gap-2">
                    <span className="font-medium text-zinc-100">{n.title}</span>
                    {!n.acknowledged ? (
                      <span className="rounded bg-amber-950/80 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-amber-200">
                        unread
                      </span>
                    ) : null}
                  </div>
                  <p className="mt-2 text-sm text-zinc-400">{n.body}</p>
                  <p className="mt-2 text-xs text-zinc-600">
                    {new Date(n.created_at).toLocaleString()} · <span className="text-zinc-500">{n.channel}</span>
                  </p>
                </div>
                {!n.acknowledged ? (
                  <button
                    type="button"
                    disabled={!userId || busy}
                    onClick={() => void acknowledge(n.id)}
                    className="shrink-0 self-start rounded-md border border-zinc-600 px-3 py-1.5 text-sm text-zinc-200 hover:bg-zinc-900 disabled:opacity-40"
                  >
                    Acknowledge
                  </button>
                ) : (
                  <span className="shrink-0 text-xs text-zinc-600">Acknowledged</span>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="mt-12">
        <h2 className="text-sm font-medium text-zinc-300">Proactive rules</h2>
        <p className="mt-2 text-sm text-zinc-500">
          Visiting this list seeds a default daily digest rule. Adjust interval (minutes); the worker enqueues
          in-app rows when due.
        </p>
        {rules.length === 0 ? (
          <p className="mt-4 text-sm text-zinc-500">Loading rules…</p>
        ) : (
          <ul className="mt-6 space-y-4">
            {rules.map((r) => (
              <li key={r.id} className="rounded-lg border border-zinc-800 bg-zinc-950/50 px-4 py-4">
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div>
                    <p className="font-medium text-zinc-100">{r.title}</p>
                    <p className="mt-1 text-xs text-zinc-500">{r.rule_type}</p>
                    <p className="mt-2 text-xs text-zinc-600">
                      Last fired:{" "}
                      {r.last_fired_at ? new Date(r.last_fired_at).toLocaleString() : "— (eligible on next tick)"}
                    </p>
                  </div>
                  <label className="flex cursor-pointer items-center gap-2 text-sm text-zinc-300">
                    <input
                      type="checkbox"
                      className="rounded border-zinc-600 bg-zinc-900"
                      checked={r.enabled}
                      disabled={busy}
                      onChange={() => void toggleRule(r)}
                    />
                    Enabled
                  </label>
                </div>
                <div className="mt-4 flex flex-wrap items-end gap-2">
                  <div>
                    <label className="text-xs uppercase tracking-wide text-zinc-500" htmlFor={`int-${r.id}`}>
                      Interval (minutes)
                    </label>
                    <input
                      id={`int-${r.id}`}
                      className="mt-1 block w-32 rounded-md border border-zinc-700 bg-zinc-900 px-2 py-1.5 font-mono text-sm text-zinc-100"
                      value={intervalDraft[r.id] ?? String(r.interval_minutes)}
                      onChange={(e) =>
                        setIntervalDraft((prev) => ({
                          ...prev,
                          [r.id]: e.target.value,
                        }))
                      }
                    />
                  </div>
                  <button
                    type="button"
                    disabled={!userId || busy}
                    onClick={() => void applyInterval(r.id)}
                    className="rounded-md bg-zinc-800 px-3 py-1.5 text-sm text-zinc-100 hover:bg-zinc-700 disabled:opacity-40"
                  >
                    Apply
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
