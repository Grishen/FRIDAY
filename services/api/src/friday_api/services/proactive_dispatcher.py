"""Create `Notification` rows from `ProactiveRule` intervals (Celery-safe)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from friday_api.models import Notification, ProactiveRule
from friday_api.persistence.sync_db import sync_session_scope


def run_proactive_tick_sync() -> dict[str, int]:
    """Evaluate enabled rules; enqueue in-app notifications when the interval elapses."""
    now = datetime.now(timezone.utc)
    created = 0
    evaluated = 0
    with sync_session_scope() as db:
        rules = list(db.scalars(select(ProactiveRule).where(ProactiveRule.enabled.is_(True))).all())
        evaluated = len(rules)
        for rule in rules:
            delta = timedelta(minutes=max(1, rule.interval_minutes))
            last = rule.last_fired_at
            if last is not None and now < last + delta:
                continue
            note = Notification(
                id=uuid.uuid4(),
                user_id=rule.user_id,
                channel="in_app",
                title=rule.title,
                body=(
                    "Time for a quick scan: open the assistant, review pending approvals, "
                    "and skim memory + documents for anything new."
                ),
                payload={
                    "rule_id": str(rule.id),
                    "rule_type": rule.rule_type,
                    "kind": "proactive_digest",
                },
                acknowledged=False,
            )
            db.add(note)
            rule.last_fired_at = now
            created += 1
    return {"notifications_created": created, "rules_evaluated": evaluated}
