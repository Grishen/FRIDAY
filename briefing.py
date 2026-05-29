"""Daily / morning briefing: weather + today's calendar + top reminders + news.

All sources are optional and degrade gracefully. When ``OPENAI_API_KEY`` is
set, the gathered facts are synthesized into a natural spoken summary via
your existing persona prompt; otherwise a clean template is returned.
"""

from __future__ import annotations

import datetime as _dt
import os
from typing import Any, Optional


def _greeting_for_hour(hour: int) -> str:
    if 0 <= hour <= 11:
        return "Good morning"
    if 12 <= hour < 18:
        return "Good afternoon"
    return "Good evening"


# ---------- weather ----------

def _openweather_for_city(city: str) -> Optional[dict[str, Any]]:
    api_key = os.environ.get("OPENWEATHER_API_KEY", "").strip()
    if not api_key or not city.strip():
        return None
    try:
        import requests
    except ImportError:
        return None
    try:
        resp = requests.get(
            "http://api.openweathermap.org/data/2.5/weather",
            params={"q": city, "appid": api_key, "units": "metric"},
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        return resp.json()
    except Exception:
        return None


def fetch_weather_summary() -> str:
    """Return a short human weather phrase (or empty if not configured)."""
    city = os.environ.get("JARVIS_DEFAULT_CITY", "").strip()
    if not city:
        return ""
    return fetch_weather_for_city(city)


def fetch_weather_for_city(city: str) -> str:
    """Return a spoken weather summary for *city*, or empty if unavailable."""
    city = (city or "").strip()
    if not city:
        return ""
    data = _openweather_for_city(city)
    if not data:
        return ""
    try:
        main = data.get("main") or {}
        weather = (data.get("weather") or [{}])[0]
        temp = round(float(main.get("temp", 0)))
        feels = round(float(main.get("feels_like", temp)))
        desc = str(weather.get("description") or "").strip()
        return f"Weather in {city}: {desc}, {temp}°C, feels like {feels}°C."
    except Exception:
        return ""


# ---------- calendar ----------

def fetch_today_calendar() -> list[dict[str, str]]:
    try:
        from calendar_service import calendar_available, calendar_today_events
    except Exception:
        return []
    if not calendar_available():
        return []
    try:
        return calendar_today_events(limit=8)
    except Exception:
        return []


# ---------- reminders ----------

def fetch_top_reminders(*, limit: int = 4) -> list[tuple[int, str, float, str]]:
    try:
        from reminders import list_pending_reminders
    except Exception:
        return []
    try:
        return list_pending_reminders(limit=limit)
    except Exception:
        return []


# ---------- news ----------

def fetch_top_headlines(*, limit: int = 4) -> list[str]:
    """
    Try NewsAPI first (NEWSAPI_KEY), else fall back to web_search for
    'top news today'.
    """
    headlines: list[str] = []
    api_key = os.environ.get("NEWSAPI_KEY", "").strip()
    if api_key:
        try:
            import requests

            resp = requests.get(
                "https://newsapi.org/v2/top-headlines",
                params={"language": "en", "pageSize": max(1, limit), "apiKey": api_key},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                for art in (data.get("articles") or [])[:limit]:
                    title = (art.get("title") or "").strip()
                    source = ((art.get("source") or {}).get("name") or "").strip()
                    if title:
                        headlines.append(f"{title} ({source})" if source else title)
        except Exception:
            pass

    if headlines:
        return headlines

    try:
        from web_search import search_web

        results = search_web("top news today", limit=max(2, limit))
        for r in results[:limit]:
            t = (r.get("title") or "").strip()
            if t:
                headlines.append(t)
    except Exception:
        pass
    return headlines


# ---------- synthesis ----------

def _template_briefing(
    *,
    greeting: str,
    weather: str,
    events: list[dict[str, str]],
    reminders_list: list[tuple[int, str, float, str]],
    headlines: list[str],
) -> str:
    parts = [f"{greeting}, Sir."]
    if weather:
        parts.append(weather)
    if events:
        ev_strs = [f"{e['title']} at {e['start']}" for e in events[:4]]
        parts.append("On your calendar today: " + "; ".join(ev_strs) + ".")
    else:
        parts.append("Your calendar is clear today.")
    if reminders_list:
        from reminders import describe_reminder_due

        rem = []
        for _rid, msg, due, recurrence in reminders_list[:4]:
            tag = f" (recurring {recurrence})" if recurrence else ""
            rem.append(f"{msg} at {describe_reminder_due(_dt.datetime.fromtimestamp(due))}{tag}")
        parts.append("Upcoming reminders: " + "; ".join(rem) + ".")
    if headlines:
        parts.append("Top headlines: " + "; ".join(headlines[:3]) + ".")
    return " ".join(parts)


def _llm_briefing(facts_text: str) -> str:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        return ""
    try:
        from openai import OpenAI
    except ImportError:
        return ""
    try:
        from jarvis_brain import brain_system_instructions

        persona = brain_system_instructions()
    except Exception:
        persona = "You are a helpful voice assistant. Be warm, concise, and grounded."

    client = OpenAI(api_key=key)
    model = os.environ.get("OPENAI_CHAT_MODEL", "gpt-4o-mini")
    sys_text = (
        persona
        + "\n\nDeliver a short morning briefing for the user. Use ONLY the FACTS provided. "
        "Sound natural and human — like a chief of staff handing off the day. "
        "Open with a warm greeting, then weather (if any), calendar, reminders, then headlines. "
        "Keep it under ~10 sentences. Do not invent items. Do not list URLs."
    )
    try:
        completion = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": sys_text},
                {"role": "user", "content": "FACTS:\n" + facts_text},
            ],
            temperature=0.4,
        )
    except Exception:
        return ""
    msg = getattr(completion.choices[0].message, "content", None) or ""
    return msg.strip()


def build_daily_briefing() -> str:
    now = _dt.datetime.now()
    greeting = _greeting_for_hour(now.hour)
    weather = fetch_weather_summary()
    events = fetch_today_calendar()
    reminders_list = fetch_top_reminders(limit=4)
    headlines = fetch_top_headlines(limit=4)

    facts: list[str] = [f"Time: {now.strftime('%A %b %d, %I:%M %p')}"]
    if weather:
        facts.append(weather)
    if events:
        for e in events[:6]:
            facts.append(f"Calendar event: {e['title']} {e['start']}-{e['end']}")
    else:
        facts.append("Calendar event: (none today)")
    if reminders_list:
        from reminders import describe_reminder_due

        for _rid, msg, due, recurrence in reminders_list[:6]:
            tag = f" (recurring {recurrence})" if recurrence else ""
            facts.append(
                f"Reminder: {msg} at {describe_reminder_due(_dt.datetime.fromtimestamp(due))}{tag}"
            )
    if headlines:
        for h in headlines[:4]:
            facts.append(f"Headline: {h}")

    synthesized = _llm_briefing("\n".join(facts))
    if synthesized:
        return synthesized
    return _template_briefing(
        greeting=greeting,
        weather=weather,
        events=events,
        reminders_list=reminders_list,
        headlines=headlines,
    )


__all__ = [
    "build_daily_briefing",
    "fetch_today_calendar",
    "fetch_top_headlines",
    "fetch_top_reminders",
    "fetch_weather_for_city",
    "fetch_weather_summary",
]
