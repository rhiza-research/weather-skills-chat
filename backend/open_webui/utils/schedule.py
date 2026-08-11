import re
from typing import Optional

WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


def parse_schedule(schedule: str) -> Optional[str]:
    """Normalize a cron string or a small set of phrases to a 5-field cron."""
    if not schedule:
        return None
    text = schedule.strip().lower()
    if not text:
        return None

    parts = text.split()
    if len(parts) == 5 and all(re.fullmatch(r"[\d*/,?-]+", p) for p in parts):
        return text

    if text in {"hourly", "every hour"}:
        return "0 * * * *"
    if text in {"daily", "every day", "everyday"}:
        return "0 0 * * *"
    if text in {"weekly", "every week"}:
        return "0 0 * * 0"

    noon = re.fullmatch(r"(every day|daily|everyday) at noon", text)
    if noon:
        return "0 12 * * *"

    midnight = re.fullmatch(r"(every day|daily|everyday) at midnight", text)
    if midnight:
        return "0 0 * * *"

    daily_at = re.fullmatch(
        r"(?:every day|daily|everyday) at (\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text
    )
    if daily_at:
        hour = int(daily_at.group(1))
        minute = int(daily_at.group(2) or 0)
        mer = daily_at.group(3)
        if mer == "pm" and hour < 12:
            hour += 12
        if mer == "am" and hour == 12:
            hour = 0
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return f"{minute} {hour} * * *"

    weekly = re.fullmatch(
        r"weekly on (\w+) at (\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text
    )
    if weekly and weekly.group(1) in WEEKDAYS:
        hour = int(weekly.group(2))
        minute = int(weekly.group(3) or 0)
        mer = weekly.group(4)
        if mer == "pm" and hour < 12:
            hour += 12
        if mer == "am" and hour == 12:
            hour = 0
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return f"{minute} {hour} * * {WEEKDAYS[weekly.group(1)]}"

    return None


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
