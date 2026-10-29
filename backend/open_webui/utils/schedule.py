import re
from typing import Optional

# Standard cron day-of-week numbers: 0 (or 7) is Sunday.
WEEKDAYS = {
    "sunday": 0,
    "monday": 1,
    "tuesday": 2,
    "wednesday": 3,
    "thursday": 4,
    "friday": 5,
    "saturday": 6,
}

# APScheduler numbers days from Monday, so triggers name the days instead.
_APSCHEDULER_DAY_NAMES = ("sun", "mon", "tue", "wed", "thu", "fri", "sat")


def apscheduler_day_of_week(field: str) -> str:
    """Translate a standard cron day-of-week field for APScheduler.

    APScheduler's CronTrigger reads 0 as Monday, where cron reads it as
    Sunday. The field's days are listed by name, which both agree on.
    Raises ValueError for a day outside 0-7 or a descending range.
    """
    if field == "*":
        return field
    days: set[int] = set()
    for item in field.split(","):
        part, _, step_text = item.partition("/")
        step = int(step_text) if step_text else 1
        if step < 1:
            raise ValueError(f"Invalid day-of-week step: {item}")
        if part == "*":
            first, last = 0, 6
        else:
            start, _, end = part.partition("-")
            first = int(start)
            last = int(end) if end else (6 if step_text else first)
        if not (0 <= first <= 7 and 0 <= last <= 7) or first > last:
            raise ValueError(f"Invalid day of week: {item}")
        days.update(day % 7 for day in range(first, last + 1, step))
    return ",".join(_APSCHEDULER_DAY_NAMES[day] for day in sorted(days))


_DAY_ALIASES = {
    **{name: number for name, number in WEEKDAYS.items()},
    **{name[:3]: number for name, number in WEEKDAYS.items()},
    "tues": 2,
    "wed": 3,
    "thur": 4,
    "thurs": 4,
}


def _parse_time(text: str) -> Optional[tuple[int, int]]:
    """(hour, minute) for "9am", "6:30pm", "18:00", "noon", or "midnight"."""
    if text == "noon":
        return 12, 0
    if text == "midnight":
        return 0, 0
    match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text)
    if not match:
        return None
    hour, minute, meridiem = int(match.group(1)), int(match.group(2) or 0), match.group(3)
    if meridiem:
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if meridiem == "pm" else 0)
    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return hour, minute
    return None


def _parse_days(text: str) -> Optional[str]:
    """The day-of-month, month, and day-of-week cron fields for the day part
    of a phrase, such as "every day", "weekdays", "mondays and thursdays",
    or "monthly on the 15th"."""
    text = re.sub(r"^(?:weekly on|on|every|each)\s+", "", text).strip()
    if text in {"", "day", "daily", "everyday", "every day", "each day"}:
        return "* * *"
    if text in {"weekly", "week"}:
        return "* * 0"
    if text in {"weekday", "weekdays"}:
        return "* * 1-5"
    if text in {"weekend", "weekends"}:
        return "* * 0,6"

    monthly = re.fullmatch(
        r"(?:monthly|month)(?: on the (\d{1,2})(?:st|nd|rd|th)?)?"
        r"|the (\d{1,2})(?:st|nd|rd|th)? of (?:every|each) month",
        text,
    )
    if monthly:
        day = int(monthly.group(1) or monthly.group(2) or 1)
        return f"{day} * *" if 1 <= day <= 31 else None

    days = set()
    for word in re.split(r"\s*,\s*|\s+and\s+|\s+", text):
        word = word.removesuffix("s") if word.endswith("days") else word
        if word not in _DAY_ALIASES:
            return None
        days.add(_DAY_ALIASES[word])
    return "* * " + ",".join(str(day) for day in sorted(days))


def parse_schedule(schedule: str) -> Optional[str]:
    """Normalize a cron string or a common English phrase to a 5-field cron.

    Phrases name days, then an optional time: "every weekday at 7am",
    "mondays and thursdays at 6:30pm", "monthly on the 15th at 9am". The time
    can come first ("at 9am every day"), and leaving it out means midnight.
    "every N minutes" and "every N hours" repeat through the day.
    """
    if not schedule:
        return None
    text = " ".join(schedule.strip().lower().rstrip(".").split())
    if not text:
        return None

    parts = text.split()
    if len(parts) == 5 and all(re.fullmatch(r"[\d*/,?-]+", p) for p in parts):
        return text

    if text in {"hourly", "every hour"}:
        return "0 * * * *"
    interval = re.fullmatch(r"every (\d+) (minute|min|hour)s?", text)
    if interval:
        count, unit = int(interval.group(1)), interval.group(2)
        if unit == "hour":
            return f"0 */{count} * * *" if 1 <= count <= 23 else None
        return f"*/{count} * * * *" if 1 <= count <= 59 else None

    time_first = re.fullmatch(r"at (.+?) ((?:on |every |each )?\S.*)", text)
    if time_first and _parse_time(time_first.group(1)):
        days_text, time_text = time_first.group(2), time_first.group(1)
    else:
        days_text, _, time_text = text.partition(" at ")
    when = _parse_time(time_text) if time_text else (0, 0)
    days = _parse_days(days_text)
    if when is None or days is None:
        return None
    hour, minute = when
    return f"{minute} {hour} {days}"


def prompt_from_messages(messages: list[dict]) -> str:
    """Build a replay prompt from prior user turns, dropping the last user message."""
    user_turns = [
        (m.get("content") or "").strip()
        for m in messages
        if m.get("role") == "user" and (m.get("content") or "").strip()
    ]
    if not user_turns:
        return ""
    prior = user_turns[:-1] if len(user_turns) > 1 else user_turns
    return "\n\n".join(prior)
