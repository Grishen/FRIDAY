import Link from "next/link";

import { DocumentsConsole } from "./DocumentsConsole";

export default function DocumentsPage() {
  return (
    <div className="min-h-screen bg-gradient-to-b from-zinc-950 to-black px-6 py-10 text-zinc-100">
      <div className="mx-auto max-w-5xl">
        <p className="text-xs uppercase tracking-[0.24em] text-emerald-400">Documents · Phase 6</p>
        <div className="mt-4 flex flex-wrap items-center justify-between gap-4">
          <h1 className="text-3xl font-semibold">RAG uploads</h1>
          <Link href="/" className="text-sm text-emerald-300 hover:text-white">
            ← Assistant
          </Link>
        </div>
        <p className="mt-4 text-zinc-400">
          Chunk → mock embed → <code className="text-emerald-300">document_chunks.embedding</code> with cosine search;
          orchestration tool <code className="text-emerald-300">documents.ask</code> reads the same index.
        </p>
        <div className="mt-10">
          <DocumentsConsole />
        </div>
      </div>
    </div>
  );
}
