"""What the sidebar's Scheduled tasks section reads and writes."""

from __future__ import annotations

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from open_webui.internal.db import get_db
from open_webui.models.automations import (
    AutomationForm,
    AutomationRun,
    AutomationRuns,
    Automations,
    AutomationUserStates,
)
from open_webui.routers import automations as router
from open_webui.utils import automation_runner, automation_scheduler


class _Tasks(unittest.TestCase):
    def setUp(self):
        self.owner = f"owner-{uuid.uuid4()}"
        self.member = f"member-{uuid.uuid4()}"
        self.org = f"org-{uuid.uuid4()}"
        for target in (
            "open_webui.utils.organizations.is_member",
            "open_webui.routers.automations.is_member",
        ):
            p = patch(target, return_value=True)
            p.start()
            self.addCleanup(p.stop)

    def _task(self, name="Daily map", visibility="organization", user_id=None):
        task = Automations.insert_new_automation(
            user_id or self.owner,
            AutomationForm(
                name=name,
                prompt="Make the map.",
                organization_id=self.org,
                visibility=visibility,
            ),
        )
        self.addCleanup(Automations.delete_automation, task.id)
        return task

    def _user(self, user_id):
        return SimpleNamespace(id=user_id, role="user")


class LatestRunTest(_Tasks):
    def test_latest_run_per_task(self):
        a, b = self._task("A"), self._task("B")
        older = AutomationRuns.insert_run(a.id, status="success")
        with get_db() as db:
            db.query(AutomationRun).filter_by(id=older.id).update(
                {"started_at": older.started_at - 60}
            )
            db.commit()
        newer = AutomationRuns.insert_run(a.id, status="running")
        latest = AutomationRuns.get_latest_runs([a.id, b.id])
        self.assertEqual(latest[a.id].id, newer.id)
        self.assertNotIn(b.id, latest)


class ListForSidebarTest(_Tasks):
    def test_tasks_come_with_last_run_and_the_viewers_state(self):
        mine = self._task("Mine", visibility="private")
        shared = self._task("Shared", user_id=self.member)
        run = AutomationRuns.insert_run(mine.id, status="failure")

        items = {
            item.id: item
            for item in router.list_automations(
                user=self._user(self.owner), organization_id=self.org
            )
        }

        self.assertEqual(items[mine.id].last_run.id, run.id)
        self.assertIsNone(items[shared.id].last_run)
        # Everything visible starts pinned, shared tasks included.
        self.assertTrue(items[mine.id].pinned)
        self.assertTrue(items[shared.id].pinned)
        self.assertIsNone(items[mine.id].seen_run_id)

    def test_pin_and_seen_are_per_user(self):
        task = self._task()
        run = AutomationRuns.insert_run(task.id, status="success")
        router.set_pinned(task.id, router.PinForm(pinned=False), user=self._user(self.member))
        router.mark_seen(task.id, router.SeenForm(run_id=run.id), user=self._user(self.member))

        def item(user_id):
            return next(
                i
                for i in router.list_automations(
                    user=self._user(user_id), organization_id=self.org
                )
                if i.id == task.id
            )

        self.assertFalse(item(self.member).pinned)
        self.assertEqual(item(self.member).seen_run_id, run.id)
        self.assertTrue(item(self.owner).pinned)
        self.assertIsNone(item(self.owner).seen_run_id)

    def test_cannot_pin_a_task_you_cannot_see(self):
        private = self._task(visibility="private")
        with self.assertRaises(HTTPException):
            router.set_pinned(
                private.id, router.PinForm(pinned=False), user=self._user(self.member)
            )

    def test_deleting_a_task_drops_its_state(self):
        task = Automations.insert_new_automation(
            self.owner, AutomationForm(name="Gone", prompt="p", organization_id=self.org)
        )
        AutomationUserStates.set_state(self.owner, task.id, pinned=False)
        Automations.delete_automation(task.id)
        self.assertEqual(AutomationUserStates.get_states(self.owner, [task.id]), {})


class StartupSweepTest(_Tasks):
    def test_runs_left_running_become_errors(self):
        task = self._task()
        stuck = AutomationRuns.insert_run(task.id, status="running")
        done = AutomationRuns.insert_run(task.id, status="success")
        with patch.object(automation_scheduler.scheduler, "start"), patch.object(
            automation_scheduler.Automations, "get_enabled_scheduled", return_value=[]
        ):
            automation_scheduler.start_scheduler(app=None)
        stuck = AutomationRuns.get_run_by_id(stuck.id)
        self.assertEqual(stuck.status, "error")
        self.assertTrue(stuck.error)
        self.assertIsNotNone(stuck.finished_at)
        self.assertEqual(AutomationRuns.get_run_by_id(done.id).status, "success")


class RunEventsTest(_Tasks, unittest.IsolatedAsyncioTestCase):
    async def test_start_and_finish_are_sent_to_everyone_who_sees_the_task(self):
        task = self._task()
        run = AutomationRuns.insert_run(task.id, status="running")
        emitted = []

        async def emit(user_ids, payload):
            emitted.append((sorted(user_ids), payload))

        members = [SimpleNamespace(user_id=self.owner), SimpleNamespace(user_id=self.member)]
        with patch.object(automation_runner, "_emit_run_event", emit), patch(
            "open_webui.models.organizations.Organizations.get_members",
            return_value=members,
        ):
            await automation_runner.notify_run(task, run)

        (user_ids, payload), = emitted
        self.assertEqual(user_ids, sorted([self.owner, self.member]))
        self.assertEqual(payload["automation_id"], task.id)
        self.assertEqual(payload["organization_id"], self.org)
        self.assertEqual(payload["run"]["id"], run.id)
        self.assertEqual(payload["run"]["status"], "running")

    async def test_a_private_task_tells_only_its_owner(self):
        task = self._task(visibility="private")
        run = AutomationRuns.insert_run(task.id, status="running")
        emit = AsyncMock()
        with patch.object(automation_runner, "_emit_run_event", emit):
            await automation_runner.notify_run(task, run)
        self.assertEqual(emit.call_args.args[0], [self.owner])


if __name__ == "__main__":
    unittest.main()
