import Link from "next/link";

import { MemoryConsole } from "./MemoryConsole";

export default function MemoryPage() {
  return (
    <div className="min-h-screen bg-gradient-to-b from-zinc-950 to-black px-6 py-10 text-zinc-100">
      <div className="mx-auto max-w-5xl">
        <p className="text-xs uppercase tracking-[0.24em] text-emerald-400">Memory · Phase 3</p>
        <div className="mt-4 flex flex-wrap items-center justify-between gap-4">
          <h1 className="text-3xl font-semibold">Long-term memory</h1>
          <Link href="/" className="text-sm text-emerald-300 hover:text-white">
            ← Back to assistant
          </Link>
        </div>
        <p className="mt-4 text-zinc-400">
          Profile, episodic, semantic, and task memories — stored with mock embeddings plus a pgvector column; similarity ranks
          in-process for dev (swap to SQL-distance queries at scale).
        </p>

        <div className="mt-10">
          <MemoryConsole />
        </div>
      </div>
    </div>
  );
}
