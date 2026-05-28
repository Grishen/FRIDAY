"""Headless / headed browser automation via Playwright (optional dep).

If Playwright is not installed, every function returns an error dict so the
caller can degrade gracefully. To enable::

    pip install playwright
    playwright install chromium

API:
    open_and_extract(url, *, wait_for='', selector='', screenshot=False) -> dict
    click(url, selector, *, wait_for='', timeout_ms=8000) -> dict
    fill(url, selector, text, *, submit=False) -> dict
    screenshot(url, *, full_page=True) -> dict

The browser is launched fresh for each call (simple, predictable). For longer
flows you can call the underlying ``with_page(fn)`` directly.
"""

from __future__ import annotations

import os
import tempfile
import time
from typing import Any, Callable, Optional


def _has_playwright() -> bool:
    try:
        import playwright.sync_api  # type: ignore  # noqa: F401
        return True
    except ImportError:
        return False


def _err(msg: str) -> dict:
    return {"ok": False, "url": "", "title": "", "text": "", "screenshot_path": "", "error": msg}


def _new_context_kwargs() -> dict:
    return {
        "viewport": {"width": 1280, "height": 820},
        "user_agent": os.environ.get(
            "JARVIS_BROWSER_UA",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_0) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
        ),
    }


def with_page(fn: Callable[[Any], Any], *, headless: bool = True, timeout_ms: int = 15000) -> Any:
    """Run ``fn(page)`` inside a fresh Chromium session. Returns whatever fn returns."""
    if not _has_playwright():
        raise RuntimeError("Playwright not installed. `pip install playwright && playwright install chromium`")
    from playwright.sync_api import sync_playwright  # type: ignore

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        try:
            context = browser.new_context(**_new_context_kwargs())
            page = context.new_page()
            page.set_default_timeout(timeout_ms)
            try:
                return fn(page)
            finally:
                context.close()
        finally:
            browser.close()


def open_and_extract(url: str, *, wait_for: str = "", selector: str = "",
                     screenshot: bool = False, timeout_ms: int = 15000) -> dict:
    if not _has_playwright():
        return _err("playwright not installed")
    if not (url or "").startswith(("http://", "https://")):
        return _err(f"not an http(s) URL: {url}")

    def _do(page):
        page.goto(url, wait_until="domcontentloaded")
        if wait_for:
            try:
                page.wait_for_selector(wait_for, timeout=timeout_ms)
            except Exception:
                pass
        text = ""
        try:
            if selector:
                el = page.query_selector(selector)
                text = (el.inner_text() if el else "")
            else:
                text = page.inner_text("body") or ""
        except Exception as exc:
            text = f"[extract failed: {exc}]"
        shot_path = ""
        if screenshot:
            shot_path = os.path.join(
                tempfile.gettempdir(), f"jarvis_browser_{int(time.time()*1000)}.png"
            )
            try:
                page.screenshot(path=shot_path, full_page=True)
            except Exception:
                shot_path = ""
        return {
            "ok": True,
            "url": page.url,
            "title": page.title(),
            "text": text[:20000],
            "screenshot_path": shot_path,
            "error": None,
        }

    try:
        return with_page(_do, headless=True, timeout_ms=timeout_ms)
    except Exception as exc:
        return _err(str(exc))


def click(url: str, selector: str, *, wait_for: str = "", timeout_ms: int = 8000) -> dict:
    if not _has_playwright():
        return _err("playwright not installed")

    def _do(page):
        page.goto(url, wait_until="domcontentloaded")
        try:
            page.click(selector, timeout=timeout_ms)
        except Exception as exc:
            return _err(f"click failed: {exc}")
        if wait_for:
            try:
                page.wait_for_selector(wait_for, timeout=timeout_ms)
            except Exception:
                pass
        return {"ok": True, "url": page.url, "title": page.title(),
                "text": (page.inner_text("body") or "")[:20000],
                "screenshot_path": "", "error": None}

    try:
        return with_page(_do, headless=True, timeout_ms=timeout_ms)
    except Exception as exc:
        return _err(str(exc))


def fill(url: str, selector: str, text: str, *, submit: bool = False,
         timeout_ms: int = 8000) -> dict:
    if not _has_playwright():
        return _err("playwright not installed")

    def _do(page):
        page.goto(url, wait_until="domcontentloaded")
        try:
            page.fill(selector, text, timeout=timeout_ms)
            if submit:
                page.press(selector, "Enter")
                page.wait_for_load_state("domcontentloaded")
        except Exception as exc:
            return _err(f"fill failed: {exc}")
        return {"ok": True, "url": page.url, "title": page.title(),
                "text": (page.inner_text("body") or "")[:20000],
                "screenshot_path": "", "error": None}

    try:
        return with_page(_do, headless=True, timeout_ms=timeout_ms)
    except Exception as exc:
        return _err(str(exc))


def screenshot(url: str, *, full_page: bool = True, timeout_ms: int = 15000) -> dict:
    if not _has_playwright():
        return _err("playwright not installed")

    def _do(page):
        page.goto(url, wait_until="domcontentloaded")
        path = os.path.join(tempfile.gettempdir(), f"jarvis_screenshot_{int(time.time()*1000)}.png")
        page.screenshot(path=path, full_page=full_page)
        return {"ok": True, "url": page.url, "title": page.title(), "text": "",
                "screenshot_path": path, "error": None}

    try:
        return with_page(_do, headless=True, timeout_ms=timeout_ms)
    except Exception as exc:
        return _err(str(exc))


__all__ = ["click", "fill", "open_and_extract", "screenshot", "with_page"]
