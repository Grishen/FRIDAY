"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { apiFetch } from "@/lib/api";
import { useFridayStore } from "@/store/friday";

type SmartDevice = {
  device_key: string;
  name: string;
  room: string;
  kind: string;
  state: Record<string, unknown>;
};

export default function IntegrationsPage() {
  const { userId, setUserId } = useFridayStore();
  const [items, setItems] = useState<SmartDevice[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const bootstrap = useCallback(async () => {
    const res = (await apiFetch("/api/v1/auth/bootstrap", {
      method: "POST",
      body: JSON.stringify({ email: "integrations@example.com" }),
    })) as { user_id: string };
    setUserId(res.user_id);
  }, [setUserId]);

  const loadDevices = useCallback(async () => {
    if (!userId) return;
    setError(null);
    try {
      const res = (await apiFetch("/api/v1/smart-home/devices", { userId })) as { items: SmartDevice[] };
      setItems(res.items ?? []);
    } catch (e) {
      setError(String(e));
    }
  }, [userId]);

  useEffect(() => {
    if (!userId) void bootstrap();
  }, [bootstrap, userId]);

  useEffect(() => {
    void loadDevices();
  }, [loadDevices]);

  const toggleKind = async (device: SmartDevice) => {
    if (!userId) return;
    setBusy(true);
    setError(null);
    try {
      if (device.kind === "switch" || device.kind === "light") {
        const on =
          typeof device.state.on === "boolean" ? device.state.on : false;
        await apiFetch(`/api/v1/smart-home/devices/${encodeURIComponent(device.device_key)}`, {
          method: "PATCH",
          userId,
          body: JSON.stringify({ state: { on: !on } }),
        });
      } else if (device.kind === "lock") {
        const locked =
          typeof device.state.locked === "boolean" ? device.state.locked : true;
        await apiFetch(`/api/v1/smart-home/devices/${encodeURIComponent(device.device_key)}`, {
          method: "PATCH",
          userId,
          body: JSON.stringify({ state: { locked: !locked } }),
        });
      }
      await loadDevices();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-5xl px-6 py-16 text-zinc-100">
      <p className="text-xs uppercase tracking-[0.24em] text-emerald-400">Integrations</p>
      <h1 className="mt-3 text-3xl font-semibold">OAuth & connectors</h1>
      <p className="mt-4 text-zinc-400">
        Third‑party connectors stay behind provider abstractions. Below is the Phase&nbsp;11 <strong className="text-zinc-200">stub</strong>{" "}
        smart home shelf—same devices are exposed over REST (<code className="text-emerald-300">/smart-home/devices</code>) and planner
        tools <code className="text-emerald-300">smarthome.list_devices</code> /{" "}
        <code className="text-emerald-300">smarthome.set_device_state</code>.{" "}
        <Link className="text-emerald-400 hover:underline" href="/">
          Chat
        </Link>
      </p>

      {error ? (
        <p className="mt-8 rounded border border-red-900/60 bg-red-950/40 px-4 py-2 text-sm text-red-200">{error}</p>
      ) : null}

      <section className="mt-12">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-zinc-800 pb-4">
          <h2 className="text-sm font-medium text-zinc-300">Smart home (stub hub)</h2>
          <button
            type="button"
            disabled={!userId || busy}
            className="rounded-md border border-zinc-700 px-3 py-1.5 text-sm text-zinc-200 hover:bg-zinc-900 disabled:opacity-40"
            onClick={() => void loadDevices()}
          >
            Refresh devices
          </button>
        </div>
        {items.length === 0 ? (
          <p className="mt-6 text-sm text-zinc-500">No stub devices loaded — bootstrap or check API migrations.</p>
        ) : (
          <ul className="mt-6 space-y-4">
            {items.map((d) => (
              <li key={d.device_key} className="rounded-lg border border-zinc-800 bg-zinc-950/50 px-4 py-4">
                <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                  <div>
                    <p className="font-medium text-zinc-100">{d.name}</p>
                    <p className="text-xs text-zinc-500">
                      {d.room} · <span className="text-emerald-400/90">{d.kind}</span> ·{" "}
                      <span className="font-mono text-zinc-600">{d.device_key}</span>
                    </p>
                  </div>
                  <div className="flex shrink-0 gap-2">
                    {d.kind === "light" || d.kind === "switch" ? (
                      <button
                        type="button"
                        disabled={!userId || busy}
                        onClick={() => void toggleKind(d)}
                        className={`rounded-md px-4 py-1.5 text-sm font-medium ${
                          typeof d.state.on === "boolean" && d.state.on ? "bg-amber-500 text-zinc-900" : "bg-zinc-800 text-zinc-200"
                        }`}
                      >
                        {typeof d.state.on === "boolean" && d.state.on ? "Turn off" : "Turn on"}
                      </button>
                    ) : null}
                    {d.kind === "lock" ? (
                      <button
                        type="button"
                        disabled={!userId || busy}
                        onClick={() => void toggleKind(d)}
                        className={`rounded-md px-4 py-1.5 text-sm font-medium ${
                          typeof d.state.locked === "boolean" && d.state.locked
                            ? "bg-rose-800 text-white"
                            : "bg-emerald-800 text-white"
                        }`}
                      >
                        {typeof d.state.locked === "boolean" && d.state.locked ? "Locked" : "Unlocked"}
                      </button>
                    ) : null}
                  </div>
                </div>
                <pre className="mt-3 overflow-x-auto rounded-md border border-zinc-800 bg-black/40 p-3 font-mono text-xs text-zinc-400">
                  {JSON.stringify(d.state, null, 2)}
                </pre>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
