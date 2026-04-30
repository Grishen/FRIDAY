"use client";

export function ApprovalModal(props: {
  open: boolean;
  toolName?: string | null;
  busy?: boolean;
  errorText?: string | null;
  onApprove: () => void | Promise<void>;
  onDeny: () => void | Promise<void>;
}) {
  if (!props.open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur">
      <div className="w-full max-w-lg rounded-xl border border-white/10 bg-zinc-900 p-6 shadow-2xl">
        <h3 className="text-lg font-semibold text-white">Approve high-risk tool</h3>
        <p className="mt-2 text-sm text-zinc-300">
          The planner requested{" "}
          <span className="font-mono text-emerald-300">{props.toolName ?? "a tool"}</span>. This queues a
          mocked handler after you confirm; the decision is written to the audit log.
        </p>
        {props.errorText ? (
          <p className="mt-3 rounded-lg border border-rose-500/40 bg-rose-950/40 px-3 py-2 text-sm text-rose-100">
            {props.errorText}
          </p>
        ) : null}
        <div className="mt-6 flex justify-end gap-3">
          <button
            type="button"
            disabled={props.busy}
            className="rounded-md border border-white/15 px-4 py-2 text-sm text-zinc-200 hover:bg-white/5 disabled:opacity-40"
            onClick={() => void props.onDeny()}
          >
            Deny
          </button>
          <button
            type="button"
            disabled={props.busy}
            className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500 disabled:opacity-40"
            onClick={() => void props.onApprove()}
          >
            {props.busy ? "Working…" : "Approve"}
          </button>
        </div>
      </div>
    </div>
  );
}
