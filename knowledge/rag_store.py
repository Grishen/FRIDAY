"""
RAG over local .txt / .md files.

Vector store (pick one):

- ChromaDB (default): persistent under data/jarvis_chroma/.
- Postgres + pgvector: set JARVIS_VECTOR_BACKEND=postgres and DATABASE_URL (or POSTGRES_* env).

Embeddings: OpenAI if OPENAI_API_KEY is set, else sentence-transformers (MiniLM).

Env:
  JARVIS_KNOWLEDGE_DIR — folder to index (default ./knowledge_docs)
  JARVIS_CHUNK_MAX_CHARS — chunk size when splitting documents (see fs_index.chunk_max_chars)
  JARVIS_VECTOR_BACKEND — chroma (default) or postgres
  DATABASE_URL — postgresql://... (postgres backend)

  OPENAI_API_KEY — recommended for embeddings + natural answers
  OPENAI_CHAT_MODEL — default gpt-4o-mini
  OPENAI_EMBEDDING_MODEL — default text-embedding-3-small
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from knowledge import fs_index
from knowledge.retrieval import expand_query, hybrid_rerank, merge_unique_results

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_CHROMA_DIR = _DATA_DIR / "jarvis_chroma"


def _vector_backend() -> str:
    raw = os.environ.get("JARVIS_VECTOR_BACKEND", "chroma").strip().lower()
    if raw in ("postgres", "postgresql", "pg"):
        return "postgres"
    return "chroma"


def _embedding_function():
    import chromadb.utils.embedding_functions as ef

    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if key:
        model = os.environ.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
        return ef.OpenAIEmbeddingFunction(api_key=key, model_name=model)
    return ef.SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")


def _persistent_client():
    import chromadb

    _CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(_CHROMA_DIR))


def _collection(*, reset: bool = False):
    client = _persistent_client()
    if reset:
        try:
            client.delete_collection("jarvis_kb")
        except Exception:
            pass
    return client.get_or_create_collection(
        name="jarvis_kb",
        embedding_function=_embedding_function(),
        metadata={"hnsw:space": "cosine"},
    )


def sync_knowledge_folder() -> int:
    """Re-index knowledge dir if needed. Returns chunk count indexed this run."""
    if _vector_backend() == "postgres":
        from knowledge import postgres_kb

        return postgres_kb.sync_from_disk()

    root = fs_index.knowledge_dir()
    files = fs_index.collect_files(root)
    state = fs_index.manifest_state(files)
    chroma_token = "chroma"
    if not fs_index.needs_vector_resync(chroma_token, state):
        return 0

    col = _collection(reset=True)

    ids: list[str] = []
    documents: list[str] = []
    metadatas: list[dict] = []
    n = 0
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        try:
            rel = str(path.relative_to(root))
        except ValueError:
            rel = path.name
        for i, chunk in enumerate(fs_index.chunk_text(text)):
            cid = hashlib.sha256(f"{rel}|{i}|{chunk[:80]}".encode()).hexdigest()[:40]
            ids.append(cid)
            documents.append(chunk)
            metadatas.append({"source": rel, "chunk": str(i)})
            n += 1

    if documents:
        col.add(ids=ids, documents=documents, metadatas=metadatas)
    fs_index.write_manifest(state)
    fs_index.write_vector_backend_marker(chroma_token)
    return n


def _collection_document_count(collection) -> int:
    try:
        return max(0, int(collection.count()))
    except Exception:
        try:
            got = collection.get(limit=999999)
            ids = got.get("ids") if isinstance(got, dict) else None
            return len(ids) if ids else 0
        except Exception:
            return 0


def _retrieve(question: str, collection, k: int = 10) -> tuple[list[str], list[str]]:
    cnt = _collection_document_count(collection)
    if cnt == 0:
        return [], []
    take = max(1, min(k, cnt))
    res = collection.query(query_texts=[question], n_results=take)
    docs = (res.get("documents") or [[]])[0] or []
    sources = (res.get("metadatas") or [[]])[0] or []
    src_labels: list[str] = []
    for m in sources:
        if isinstance(m, dict) and m.get("source"):
            src_labels.append(str(m["source"]))
        else:
            src_labels.append("unknown")
    return docs, src_labels


def _retrieve_hybrid(question: str, collection, *, pool_k: int = 10, top_k: int = 6) -> tuple[list[str], list[str]]:
    docs_a, src_a = _retrieve(question, collection, k=pool_k)
    expanded = " ".join(sorted(expand_query(question)))
    if expanded and expanded.lower() != question.strip().lower():
        docs_b, src_b = _retrieve(expanded, collection, k=pool_k)
        merged_docs, merged_src = merge_unique_results(
            docs_a, src_a, docs_b, src_b, max_total=pool_k * 2
        )
    else:
        merged_docs, merged_src = docs_a, src_a
    return hybrid_rerank(question, merged_docs, merged_src, top_k=top_k)


def knowledge_document_count() -> int:
    root = fs_index.knowledge_dir()
    return len(fs_index.collect_files(root))


def knowledge_indexed_chunk_count() -> int:
    if _vector_backend() == "postgres":
        from knowledge import postgres_kb

        return postgres_kb.indexed_chunk_count()
    return _collection_document_count(_collection())


def force_resync_knowledge() -> int:
    """Force a full re-index regardless of manifest state."""
    if _vector_backend() == "postgres":
        from knowledge import postgres_kb

        root = fs_index.knowledge_dir()
        files = fs_index.collect_files(root)
        state = fs_index.manifest_state(files)
        fs_index.write_manifest({})  # force mismatch
        return postgres_kb.sync_from_disk()

    root = fs_index.knowledge_dir()
    files = fs_index.collect_files(root)
    state = fs_index.manifest_state(files)
    fs_index.write_manifest({})
    col = _collection(reset=True)
    ids: list[str] = []
    documents: list[str] = []
    metadatas: list[dict] = []
    n = 0
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        try:
            rel = str(path.relative_to(root))
        except ValueError:
            rel = path.name
        for i, chunk in enumerate(fs_index.chunk_text(text)):
            cid = hashlib.sha256(f"{rel}|{i}|{chunk[:80]}".encode()).hexdigest()[:40]
            ids.append(cid)
            documents.append(chunk)
            metadatas.append({"source": rel, "chunk": str(i)})
            n += 1
    if documents:
        col.add(ids=ids, documents=documents, metadatas=metadatas)
    fs_index.write_manifest(state)
    fs_index.write_vector_backend_marker("chroma")
    return n


def describe_knowledge_for_voice() -> str:
    root = fs_index.knowledge_dir()
    docs = knowledge_document_count()
    chunks = knowledge_indexed_chunk_count()
    backend = _vector_backend()
    return (
        f"Knowledge base status: backend {backend}, folder {root}, "
        f"{docs} source files indexed into {chunks} chunks."
    )


def _synthesize_with_openai(question: str, context: str) -> str:
    from openai import OpenAI

    try:
        from jarvis_brain import brain_system_instructions
    except ImportError:
        def brain_system_instructions() -> str:  # type: ignore[misc]
            return "You are a helpful voice assistant. Be natural, concise, and grounded."

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    model = os.environ.get("OPENAI_CHAT_MODEL", "gpt-4o-mini")
    msg = (
        brain_system_instructions()
        + "\n\nYou are answering from the user's LOCAL DOCUMENTS only. "
        "Use ONLY the provided CONTEXT. If the answer is missing, say so plainly and suggest "
        "what document or detail would help. Do not invent facts. "
        "Sound natural for speech: warm, clear, and human — not robotic."
    )
    completion = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": msg},
            {
                "role": "user",
                "content": f"CONTEXT:\n{context}\n\nQUESTION:\n{question}",
            },
        ],
        temperature=0.35,
    )
    content = getattr(completion.choices[0].message, "content", None)
    reply = (content or "").strip()
    if reply:
        return reply
    return "I formed no verbal answer from that context, Sir. Try asking more specifically."


def answer_from_knowledge(question: str) -> str:
    """Retrieve + optional LLM synthesis; safe to pass to speak()."""
    question = (question or "").strip()
    kb_root = fs_index.knowledge_dir()
    if not question:
        return "Please ask a specific question for the knowledge base, Sir."

    sync_knowledge_folder()

    if _vector_backend() == "postgres":
        from knowledge import postgres_kb

        try:
            if postgres_kb.indexed_chunk_count() == 0:
                return (
                    "There are no indexed documents yet, Sir. Add text or markdown files under "
                    f"{kb_root} and say a knowledge command again."
                )
            raw_chunks, raw_sources = postgres_kb.postgres_retrieve(question, k=10)
            chunks, sources = hybrid_rerank(question, raw_chunks, raw_sources, top_k=6)
        except Exception as exc:
            return (
                f"Sir, Postgres knowledge lookup failed ({exc}). "
                "Check DATABASE_URL, pgvector extension, and embedding configuration."
            )
    else:
        collection = _collection()
        doc_count = _collection_document_count(collection)
        if doc_count == 0:
            return (
                "There are no indexed documents yet, Sir. Add text or markdown files under "
                f"{kb_root} and say a knowledge command again."
            )
        chunks, sources = _retrieve_hybrid(question, collection, pool_k=10, top_k=6)

    if not chunks:
        return "I could not find relevant passages in your documents, Sir."

    context = "\n\n---\n\n".join(
        f"[{sources[i]}]\n{c}" for i, c in enumerate(chunks)
    )

    if os.environ.get("OPENAI_API_KEY", "").strip():
        try:
            return _synthesize_with_openai(question, context)
        except Exception as exc:
            return f"Synthesis failed ({exc}). Here's what matched: {' '.join(chunks[:2])[:1200]}"

    excerpt = chunks[0][:1500]
    if len(chunks) > 1:
        excerpt += " ... " + chunks[1][:500]
    return f"Sir, according to your documents: {excerpt}"
