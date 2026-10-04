"""Read when a usage limit resets from Claude Code's limit message.

Claude Code has phrased this several ways (e.g. "usage limit reached|1759683600", "resets 3pm",
"resets 3:30pm (Asia/Karachi)", "resets Oct 6, 9am", "resets Mon 9am", or an ISO timestamp).
Times without a timezone are taken as UTC, the agent container's clock. Returns None when nothing
can be read, and the caller falls back to a fixed wait.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_EPOCH = re.compile(r"\|\s*(\d{10})\b")
_ISO = re.compile(r"\b(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)")
_MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_CLOCK = re.compile(
    r"resets?\s+(?:at\s+|on\s+)?"
    r"(?:(?P<wday>mon|tue|wed|thu|fri|sat|sun)[a-z]*,?\s+)?"
    r"(?:(?P<mon>jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(?P<dom>\d{1,2}),?\s+(?:at\s+)?)?"
    r"(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<ap>am|pm)?"
    r"(?:\s*\((?P<tz>[A-Za-z_]+(?:/[A-Za-z_+-]+)*)\))?",
    re.IGNORECASE)


def _zone(name: str | None):
    if not name:
        return UTC
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return UTC


def reset_time(text: str, now: datetime) -> datetime | None:
    """The reset moment in UTC, or None. `now` must be timezone-aware."""
    if not text:
        return None
    if m := _EPOCH.search(text):
        return datetime.fromtimestamp(int(m.group(1)), UTC)
    if m := _ISO.search(text):
        try:
            stamp = datetime.fromisoformat(m.group(1).replace("Z", "+00:00").replace(" ", "T"))
            return (stamp if stamp.tzinfo else stamp.replace(tzinfo=UTC)).astimezone(UTC)
        except ValueError:
            pass
    m = _CLOCK.search(text)
    if not m:
        return None
    hour, minute = int(m.group("h")), int(m.group("m") or 0)
    ap = (m.group("ap") or "").lower()
    if ap == "pm" and hour != 12:
        hour += 12
    elif ap == "am" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return None
    zone = _zone(m.group("tz"))
    local_now = now.astimezone(zone)
    if m.group("mon"):
        month = _MONTHS.index(m.group("mon").lower()[:3]) + 1
        candidate = local_now.replace(month=month, day=int(m.group("dom")), hour=hour, minute=minute,
                                      second=0, microsecond=0)
        if candidate <= local_now:
            candidate = candidate.replace(year=candidate.year + 1)
    else:
        candidate = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if m.group("wday"):
            ahead = (_DAYS.index(m.group("wday").lower()[:3]) - local_now.weekday()) % 7
            candidate += timedelta(days=ahead)
            if candidate <= local_now:
                candidate += timedelta(days=7)
        elif candidate <= local_now:
            candidate += timedelta(days=1)
    return candidate.astimezone(UTC)


def latest_reset(messages: list[str], now: datetime) -> datetime | None:
    """The latest future reset among several limit messages (so every limit has cleared)."""
    times = [t for t in (reset_time(msg, now) for msg in messages) if t and t > now]
    return max(times) if times else None
