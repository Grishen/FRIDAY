import Link from "next/link";

import { apiBase } from "@/lib/config";

import { AuditPanel } from "./AuditPanel";

export default function DebugPage() {
  return (
    <div className="mx-auto max-w-5xl px-6 py-16 text-zinc-100">
      <p className="text-xs uppercase tracking-[0.24em] text-emerald-400">Audit · Phase 4</p>
      <h1 className="mt-3 text-3xl font-semibold">Operator panel</h1>
      <p className="mt-4 max-w-xl text-zinc-400">
        API base: <span className="font-mono text-emerald-300">{apiBase}</span>
      </p>
      <p className="mt-2 text-sm text-zinc-500">
        Platform probes and OpenAPI links:{" "}
        <Link className="text-emerald-400 hover:underline" href="/dev">
          /dev
        </Link>
      </p>

      <AuditPanel />
    </div>
  );
}
