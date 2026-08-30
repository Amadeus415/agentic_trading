"""UTC session slots for the short-term scheduled paper book.

Keep this mapping in sync with `scripts/run_scheduled_cycle.sh`.
"""

from __future__ import annotations

from datetime import UTC, datetime

SESSION_EU = "session-eu"
SESSION_US_OPEN = "session-us-open"
SESSION_US_CLOSE = "session-us-close"
SESSION_OFFHOURS = "session-offhours"

# Inclusive start hour, exclusive end hour, in UTC.
_SESSION_WINDOWS: tuple[tuple[int, int, str], ...] = (
    (13, 16, SESSION_EU),
    (16, 20, SESSION_US_OPEN),
    (20, 23, SESSION_US_CLOSE),
)


def scheduled_slot(now: datetime | None = None) -> str:
    """Return the named trading session for a UTC timestamp."""
    moment = _ensure_utc(now)
    hour = moment.hour
    for start, end, slot in _SESSION_WINDOWS:
        if start <= hour < end:
            return slot
    return SESSION_OFFHOURS


def scheduled_cycle_key(now: datetime | None = None) -> str:
    """Return the scheduled cycle key for the current UTC session."""
    moment = _ensure_utc(now)
    return f"{moment.date().isoformat()}-{scheduled_slot(moment)}"


def scheduled_input_path(now: datetime | None = None) -> str:
    """Repo-relative default packet path for the current UTC session."""
    return f"state/fund-inputs/{scheduled_cycle_key(now)}.json"


def _ensure_utc(now: datetime | None) -> datetime:
    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        raise ValueError("scheduled timestamps must include a timezone")
    return moment.astimezone(UTC)
