"""Schedules typed as common English phrases become 5-field cron."""

from __future__ import annotations

import unittest

from open_webui.utils.schedule import parse_schedule

CASES = {
    # Phrases that already worked keep working.
    "hourly": "0 * * * *",
    "daily": "0 0 * * *",
    "weekly": "0 0 * * 0",
    "every day at noon": "0 12 * * *",
    "daily at 6:30pm": "30 18 * * *",
    "weekly on Monday at 9am": "0 9 * * 1",
    # Several days, weekdays, weekends.
    "every monday and thursday at 6am": "0 6 * * 1,4",
    "Mondays and Thursdays at 6am": "0 6 * * 1,4",
    "mon, wed and fri at 7:15": "15 7 * * 1,3,5",
    "every weekday at 7am": "0 7 * * 1-5",
    "weekdays at 18:30": "30 18 * * 1-5",
    "every weekend at 10am": "0 10 * * 0,6",
    "every sunday": "0 0 * * 0",
    # Time first.
    "at 9am every day": "0 9 * * *",
    "at 8pm on fridays": "0 20 * * 5",
    # Intervals.
    "every 15 minutes": "*/15 * * * *",
    "every 2 hours": "0 */2 * * *",
    "every hour": "0 * * * *",
    # Monthly.
    "monthly": "0 0 1 * *",
    "monthly on the 15th at 9am": "0 9 15 * *",
    "every month on the 1st": "0 0 1 * *",
    "on the 1st of every month at 6am": "0 6 1 * *",
    # Cron passes through.
    "0 6 * * 1,4": "0 6 * * 1,4",
}

REJECTED = [
    "whenever",
    "every 0 minutes",
    "every 90 minutes",
    "every monday at 25:00",
    "monthly on the 32nd",
    "every funday at 6am",
]


class SchedulePhraseTest(unittest.TestCase):
    def test_phrases(self):
        for phrase, cron in CASES.items():
            with self.subTest(phrase=phrase):
                self.assertEqual(parse_schedule(phrase), cron)

    def test_rejected(self):
        for phrase in REJECTED:
            with self.subTest(phrase=phrase):
                self.assertIsNone(parse_schedule(phrase))


if __name__ == "__main__":
    unittest.main()
