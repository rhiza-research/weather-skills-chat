"""Automation schedules use standard cron weekdays: 0 and 7 are Sunday."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from open_webui.utils.automation_scheduler import cron_trigger
from open_webui.utils.schedule import parse_schedule

# A Tuesday.
START = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)


def _fire_days(cron: str, count: int = 7) -> list[str]:
    trigger = cron_trigger(cron, timezone="UTC")
    days, previous, now = [], None, START
    for _ in range(count):
        fire = trigger.get_next_fire_time(previous, now)
        days.append(fire.strftime("%a"))
        previous, now = fire, fire + timedelta(seconds=1)
    return days


class WeekdayPhraseTest(unittest.TestCase):
    def test_weekday_phrases_use_standard_numbers(self):
        self.assertEqual(parse_schedule("weekly on Monday at 9am"), "0 9 * * 1")
        self.assertEqual(parse_schedule("weekly on Thursday at 6:30pm"), "30 18 * * 4")
        self.assertEqual(parse_schedule("weekly on Sunday at 9am"), "0 9 * * 0")


class CronTriggerWeekdayTest(unittest.TestCase):
    def test_single_days(self):
        self.assertEqual(_fire_days("0 6 * * 1", 2), ["Mon", "Mon"])
        self.assertEqual(_fire_days("0 6 * * 0", 1), ["Sun"])
        self.assertEqual(_fire_days("0 6 * * 7", 1), ["Sun"])
        self.assertEqual(_fire_days("0 6 * * 6", 1), ["Sat"])

    def test_list(self):
        # Genevieve's ECMWF S2S automation: Mondays and Thursdays.
        self.assertEqual(_fire_days("0 6 * * 1,4", 4), ["Thu", "Mon", "Thu", "Mon"])

    def test_range_and_step(self):
        self.assertEqual(
            _fire_days("0 6 * * 1-5", 5), ["Wed", "Thu", "Fri", "Mon", "Tue"]
        )
        self.assertEqual(_fire_days("0 6 * * */2", 4), ["Thu", "Sat", "Sun", "Tue"])
        self.assertEqual(_fire_days("0 6 * * 0-6/3", 3), ["Wed", "Sat", "Sun"])

    def test_every_day_is_unchanged(self):
        self.assertEqual(len(set(_fire_days("0 12 * * *", 7))), 7)

    def test_phrase_round_trip(self):
        self.assertEqual(
            _fire_days(parse_schedule("weekly on Monday at 9am"), 1), ["Mon"]
        )

    def test_out_of_range_day_is_rejected(self):
        with self.assertRaises(ValueError):
            cron_trigger("0 6 * * 8")
        with self.assertRaises(ValueError):
            cron_trigger("0 6 * * 5-1")


if __name__ == "__main__":
    unittest.main()


class SchedulesRunInUtcTest(unittest.TestCase):
    def test_jobs_use_utc_whatever_the_machine_zone(self):
        from unittest.mock import patch

        from open_webui.utils import automation_scheduler

        task = type("Task", (), {"id": "t1", "enabled": True, "cron": "0 6 * * 1"})()
        with patch.object(automation_scheduler.scheduler, "get_job", return_value=None), patch.object(
            automation_scheduler.scheduler, "add_job"
        ) as add_job:
            automation_scheduler.sync_automation_job(task)
        self.assertEqual(str(add_job.call_args.kwargs["trigger"].timezone), "UTC")
