"""Fetch a web page into the local knowledge_docs tree as plain text.

Requires optional ``requests`` (usually already installed with this project).
Files land in ``knowledge_docs/_ingested_urls/``.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from urllib.parse import urlparse


def ingest_url_into_knowledge(url: str, *, timeout: float = 25.0) -> str:
    """Download *url*, strip rough HTML-ish text, save under ``knowledge_docs/_ingested_urls/``."""
    u = (url or "").strip()
    if not u.startswith(("http://", "https://")):
        return "Only http/https URLs can be ingested."

    try:
        import requests
    except ImportError:
        return "Install requests to ingest URLs: pip install requests"

    from knowledge.fs_index import knowledge_dir

    try:
        r = requests.get(
            u,
            timeout=timeout,
            headers={
                "User-Agent": "JarvisKnowledgeBot/1.0 (+local assistant)"
            },
        )
        r.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        return f"Download failed: {exc}"

    raw_bytes = r.content[:2_500_000]  # cap ~2.5MB
    try:
        html = raw_bytes.decode("utf-8", errors="replace")
    except Exception:
        html = raw_bytes.decode("latin-1", errors="replace")

    cleaned = re.sub(r"(?is)<script.*?>.*?</script>", " ", html)
    cleaned = re.sub(r"(?is)<style.*?>.*?</style>", " ", cleaned)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = re.sub(r"[\t ]+", " ", cleaned)
    cleaned = re.sub(r"\n\s+", "\n", cleaned)
    cleaned = "\n".join(line.strip() for line in cleaned.splitlines() if line.strip())
    cleaned = cleaned.strip()

    host = urlparse(u).hostname or "page"
    safe_host = "".join(c if c.isalnum() or c in "-._" else "_" for c in host)[:120]
    dig = hashlib.sha256(u.encode("utf-8")).hexdigest()[:14]
    sub = Path(knowledge_dir()) / "_ingested_urls"
    sub.mkdir(parents=True, exist_ok=True)
    fname = sub / f"{safe_host}_{dig}.txt"

    fname.write_text(
        f"# Ingested from {u}\n\n{cleaned[:500_000]}",
        encoding="utf-8",
        errors="replace",
    )
    return (
        f"Saved text to knowledge_docs/_ingested_urls/{fname.name}. "
        "Resync the knowledge index so RAG/embeddings pick it up."
    )
