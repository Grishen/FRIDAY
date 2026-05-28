"""Lightweight web search helpers for the conversational brain.

Two backends, in priority order:

1. **Tavily** — if ``TAVILY_API_KEY`` is set (https://tavily.com). Returns
   structured JSON with title/url/snippet/content.
2. **DuckDuckGo HTML** — no API key required, scraped from the public
   ``html.duckduckgo.com`` results page.

Both return a normalized ``list[dict]`` so callers do not need to branch.
"""

from __future__ import annotations

import json
import os
import re
from html import unescape
from typing import Any
from urllib.parse import parse_qs, quote_plus, urlparse


_USER_AGENT = (
    "Mozilla/5.0 (compatible; JarvisWebBot/1.0; +https://example.local/jarvis) "
    "Safari/537.36"
)


def _normalize_results(items: list[dict[str, Any]], *, limit: int) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in items:
        url = str(item.get("url") or item.get("link") or "").strip()
        title = str(item.get("title") or "").strip()
        snippet = str(item.get("snippet") or item.get("content") or item.get("description") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(
            {
                "title": title[:240] or url,
                "url": url[:512],
                "snippet": snippet[:600],
            }
        )
        if len(out) >= limit:
            break
    return out


def _tavily_search(query: str, *, limit: int) -> list[dict[str, str]]:
    api_key = os.environ.get("TAVILY_API_KEY", "").strip()
    if not api_key:
        return []
    try:
        import requests
    except ImportError:
        return []
    try:
        resp = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": query,
                "max_results": max(3, min(10, limit + 2)),
                "search_depth": "basic",
                "include_answer": False,
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return []
    items = data.get("results") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    return _normalize_results(items, limit=limit)


def _duckduckgo_search(query: str, *, limit: int) -> list[dict[str, str]]:
    try:
        import requests
    except ImportError:
        return []
    try:
        resp = requests.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query},
            headers={"User-Agent": _USER_AGENT},
            timeout=15,
        )
        resp.raise_for_status()
    except Exception:
        return []

    html = resp.text
    items: list[dict[str, Any]] = []
    pattern = re.compile(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>'
        r'.*?<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
        re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(html):
        raw_url = unescape(match.group(1)).strip()
        title_html = match.group(2)
        snippet_html = match.group(3)
        url = _clean_duckduckgo_redirect(raw_url)
        title = _strip_html(title_html)
        snippet = _strip_html(snippet_html)
        if url and title:
            items.append({"url": url, "title": title, "snippet": snippet})
        if len(items) >= limit + 2:
            break
    return _normalize_results(items, limit=limit)


def _clean_duckduckgo_redirect(url: str) -> str:
    if url.startswith("//"):
        url = "https:" + url
    parsed = urlparse(url)
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        qs = parse_qs(parsed.query)
        target = qs.get("uddg")
        if target:
            from urllib.parse import unquote

            return unquote(target[0])
    return url


def _strip_html(fragment: str) -> str:
    text = re.sub(r"<[^>]+>", " ", fragment or "")
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def search_web(query: str, *, limit: int = 5) -> list[dict[str, str]]:
    """Return a deduplicated list of {title, url, snippet} for *query*."""
    q = (query or "").strip()
    if not q:
        return []
    limit = max(1, min(10, limit))
    results = _tavily_search(q, limit=limit)
    if results:
        return results
    return _duckduckgo_search(q, limit=limit)


def format_results_for_voice(results: list[dict[str, str]]) -> str:
    if not results:
        return "I could not find usable web results, Sir."
    lines: list[str] = []
    for i, r in enumerate(results, 1):
        title = r.get("title") or r.get("url") or ""
        snippet = r.get("snippet") or ""
        lines.append(f"{i}. {title}. {snippet}".strip())
    return " ".join(lines)


def format_results_as_json(results: list[dict[str, str]]) -> str:
    return json.dumps(results, ensure_ascii=False)


def encode_search_url(query: str) -> str:
    return f"https://duckduckgo.com/?q={quote_plus(query)}"
