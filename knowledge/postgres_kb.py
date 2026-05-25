"""Postgres + pgvector storage for Jarvis knowledge (alternative to Chroma).

Requires:
  - Postgres with the `vector` extension (e.g. Docker image `pgvector/pgvector:pg16`)
  - pip: psycopg, pgvector

Env:
  DATABASE_URL=postgresql://USER:PASS@HOST:5432/DB
  Or POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD

  JARVIS_VECTOR_BACKEND=postgres
  Same embedding vars as Chroma (OPENAI_API_KEY or sentence-transformers).
"""

from __future__ import annotations

import os
from collections import OrderedDict
from pathlib import Path
from uuid import UUID

import psycopg
from pgvector.psycopg import Vector, register_vector

from knowledge import fs_index
from knowledge.embeddings import embed_texts, embedding_dimension


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if url:
        return url
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    db = os.environ.get("POSTGRES_DB", "jarvis")
    user = os.environ.get("POSTGRES_USER", "jarvis")
    pw = os.environ.get("POSTGRES_PASSWORD", "")
    return f"postgresql://{user}:{pw}@{host}:{port}/{db}"


def connect():
    """Open a pooled transaction connection; pgvector extension is ensured before type registration."""
    conn = psycopg.connect(_database_url(), autocommit=True)
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
    conn.close()
    conn = psycopg.connect(_database_url(), autocommit=False)
    register_vector(conn)
    return conn


def connect_plain(*, autocommit: bool = False):
    """Postgres connection without pgvector adapters (for simple metadata tables)."""
    return psycopg.connect(_database_url(), autocommit=autocommit)


def ensure_schema(conn, dim: int) -> None:
    if dim <= 0 or dim > 8192:
        raise ValueError(f"Invalid embedding dimension: {dim}")
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS kb_documents (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                source_path TEXT NOT NULL UNIQUE,
                fs_mtime DOUBLE PRECISION NOT NULL DEFAULT 0
            )
            """
        )
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS kb_chunks (
                id BIGSERIAL PRIMARY KEY,
                document_id UUID NOT NULL REFERENCES kb_documents(id) ON DELETE CASCADE,
                chunk_index INTEGER NOT NULL,
                content TEXT NOT NULL,
                embedding vector({dim}) NOT NULL,
                UNIQUE(document_id, chunk_index)
            )
            """
        )
    conn.commit()
    _try_create_hnsw_index(conn)


def _try_create_hnsw_index(conn) -> None:
    try:
        with conn.cursor() as cur:
            cur.execute("DROP INDEX IF EXISTS kb_chunks_embedding_hnsw")
            cur.execute(
                "CREATE INDEX kb_chunks_embedding_hnsw ON kb_chunks "
                "USING hnsw (embedding vector_cosine_ops)"
            )
        conn.commit()
    except Exception:
        conn.rollback()


def postgres_chunk_count(conn) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM kb_chunks")
        row = cur.fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def indexed_chunk_count() -> int:
    """How many embeddings are stored (for empty-KB messaging)."""
    conn = connect()
    try:
        ensure_schema(conn, embedding_dimension())
        return postgres_chunk_count(conn)
    finally:
        conn.close()


def _rel_path_under_root(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return path.name


def sync_from_disk() -> int:
    """Rebuild Postgres KB when files or vector backend changed."""
    root = fs_index.knowledge_dir()
    files = fs_index.collect_files(root)
    state = fs_index.manifest_state(files)
    backend_token = "postgres"
    if not fs_index.needs_vector_resync(backend_token, state):
        return 0

    chunk_rows: list[dict[str, Any]] = []
    for path in files:
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = _rel_path_under_root(root, path)
        mt = float(path.stat().st_mtime)
        for i, chunk in enumerate(fs_index.chunk_text(raw)):
            chunk_rows.append({"rel": rel, "mtime": mt, "idx": i, "content": chunk})

    conn = connect()
    try:
        dim = embedding_dimension()
        ensure_schema(conn, dim)

        if not chunk_rows:
            with conn.cursor() as cur:
                cur.execute("TRUNCATE kb_chunks, kb_documents RESTART IDENTITY CASCADE")
            conn.commit()
            fs_index.write_manifest(state)
            fs_index.write_vector_backend_marker(backend_token)
            return 0

        texts = [r["content"] for r in chunk_rows]
        vectors = embed_texts(texts)
        if any(len(v) != dim for v in vectors):
            raise RuntimeError(
                "Embedding lengths do not match JARVIS_EMBEDDING_DIMENSION / model defaults."
            )

        uniq_docs = OrderedDict()
        for r in chunk_rows:
            uniq_docs.setdefault(r["rel"], r["mtime"])

        uuid_by_rel: dict[str, UUID] = {}
        with conn.cursor() as cur:
            cur.execute("TRUNCATE kb_chunks, kb_documents RESTART IDENTITY CASCADE")
            for rel, mt in uniq_docs.items():
                cur.execute(
                    """
                    INSERT INTO kb_documents (source_path, fs_mtime)
                    VALUES (%s, %s)
                    RETURNING id
                    """,
                    (rel, mt),
                )
                uuid_by_rel[rel] = cur.fetchone()[0]

            payload = []
            for row, vec in zip(chunk_rows, vectors):
                payload.append((uuid_by_rel[row["rel"]], row["idx"], row["content"], vec))

            cur.executemany(
                """
                INSERT INTO kb_chunks (document_id, chunk_index, content, embedding)
                VALUES (%s, %s, %s, %s)
                """,
                payload,
            )

        conn.commit()
        fs_index.write_manifest(state)
        fs_index.write_vector_backend_marker(backend_token)
        return len(chunk_rows)
    finally:
        conn.close()


def postgres_retrieve(question: str, k: int = 6) -> tuple[list[str], list[str]]:
    conn = connect()
    try:
        dim = embedding_dimension()
        ensure_schema(conn, dim)
        cnt = postgres_chunk_count(conn)
        if cnt == 0:
            return [], []

        vec = embed_texts([question.strip()])[0]
        if len(vec) != dim:
            raise RuntimeError("Query embedding dimension mismatch.")

        take = max(1, min(k, cnt))
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT c.content, d.source_path
                FROM kb_chunks c
                JOIN kb_documents d ON d.id = c.document_id
                ORDER BY c.embedding <=> %(q)s
                LIMIT %(lim)s
                """,
                {"q": Vector(vec), "lim": take},
            )
            rows = cur.fetchall()
        contents = [r[0] for r in rows]
        paths = [r[1] for r in rows]
        return contents, paths
    finally:
        conn.close()


def backend_available() -> bool:
    if not _database_url().strip():
        return False
    try:
        psycopg.connect(_database_url(), connect_timeout=3).close()
        return True
    except Exception:
        return False
