"""Tool runner sizes: the catalog, a chat's chosen size, switching, and the request_tool_runner tool."""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

from open_webui.utils import runner_types
from open_webui.utils import skill_k8s_sandbox as k8s
from open_webui.utils.runner_types import RunnerType

K = "open_webui.utils.skill_k8s_sandbox"


def _template(rtype, name, *, order, warm="true", approval="false", ttl="600", cpu="8", memory="8Gi"):
    return {
        "metadata": {
            "name": name,
            "labels": {runner_types.TYPE_LABEL: rtype},
            "annotations": {
                "weather-skills.org/display-name": rtype.title(),
                "weather-skills.org/description": f"{rtype} runner",
                "weather-skills.org/order": str(order),
                "weather-skills.org/warm": warm,
                "weather-skills.org/start-timeout-seconds": "300",
                "weather-skills.org/idle-ttl-seconds": ttl,
                "weather-skills.org/requires-approval": approval,
            },
        },
        "spec": {
            "podTemplate": {
                "spec": {
                    "containers": [
                        {"name": "runner", "resources": {"limits": {"cpu": cpu, "memory": memory}}}
                    ]
                }
            }
        },
    }


TEMPLATES = [
    _template("large", "weather-skills-large-runner", order=3, warm="false", approval="true", ttl="300", memory="52Gi"),
    _template("standard", "weather-skills-standard-runner", order=1),
    _template("medium", "weather-skills-medium-runner", order=2, warm="false", memory="16Gi"),
]


def _catalog() -> list[RunnerType]:
    sizes = [runner_types.from_template(t, k8s._runner_limits(t)) for t in TEMPLATES]
    return sorted(sizes, key=lambda t: t.order)


STANDARD, MEDIUM, LARGE = _catalog()


class CatalogTest(TestCase):
    def test_reads_the_infra_annotations(self):
        self.assertEqual(LARGE.type, "large")
        self.assertEqual(LARGE.name, "weather-skills-large-runner")
        self.assertEqual(LARGE.display_name, "Large")
        self.assertEqual(LARGE.order, 3)
        self.assertFalse(LARGE.warm)
        self.assertTrue(LARGE.requires_approval)
        self.assertEqual(LARGE.idle_ttl_seconds, 300)
        self.assertEqual(LARGE.start_timeout_seconds, 300)
        self.assertEqual((LARGE.cpus, LARGE.memory_gib), (8.0, 52.0))
        self.assertTrue(STANDARD.warm)
        self.assertFalse(STANDARD.requires_approval)

    def test_a_template_without_the_type_label_is_not_a_size(self):
        self.assertIsNone(runner_types.from_template({"metadata": {"name": "x"}}, None))

    def test_find_by_type_or_display_name(self):
        catalog = _catalog()
        self.assertEqual(runner_types.find(catalog, "LARGE"), LARGE)
        self.assertEqual(runner_types.find(catalog, "Medium"), MEDIUM)
        self.assertIsNone(runner_types.find(catalog, "huge"))

    def test_sizes_needing_approval_are_for_allowed_organizations(self):
        catalog = _catalog()
        plain = SimpleNamespace(kind="workspace", can_use_large_runners=False)
        allowed = SimpleNamespace(kind="workspace", can_use_large_runners=True)
        platform = SimpleNamespace(kind="platform", can_use_large_runners=False)
        self.assertEqual(runner_types.allowed_for_org(catalog, plain), [STANDARD, MEDIUM])
        self.assertEqual(runner_types.allowed_for_org(catalog, allowed), catalog)
        self.assertEqual(runner_types.allowed_for_org(catalog, platform), catalog)
        self.assertEqual(runner_types.allowed_for_org(catalog, None), [STANDARD, MEDIUM])


class CatalogReadTest(IsolatedAsyncioTestCase):
    def setUp(self):
        k8s._catalog_cache = None

    def tearDown(self):
        k8s._catalog_cache = None

    async def test_lists_templates_by_label_cheapest_first(self):
        k8s_call = AsyncMock(return_value={"items": TEMPLATES})
        with patch(f"{K}._k8s", k8s_call):
            sizes = await k8s.runner_catalog()
        self.assertEqual([t.type for t in sizes], ["standard", "medium", "large"])
        self.assertIn("labelSelector=weather-skills.org%2Frunner-type", k8s_call.await_args.args[1])
        self.assertEqual(k8s.default_runner_type(sizes).type, "standard")

    async def test_no_catalog_falls_back_to_the_default_pool(self):
        calls = [{"items": []}, TEMPLATES[1]]
        with patch(f"{K}._k8s", AsyncMock(side_effect=calls)):
            sizes = await k8s.runner_catalog()
        self.assertEqual(len(sizes), 1)
        self.assertEqual(sizes[0].name, k8s._pool())
        self.assertEqual(sizes[0].memory_gib, 8.0)


class ChoiceTest(TestCase):
    def tearDown(self):
        runner_types._choices.clear()

    def test_a_choice_ends_after_its_time(self):
        runner_types.choose("c1", LARGE, 60)
        self.assertEqual(runner_types.chosen("c1"), LARGE)
        runner_types._choices["c1"] = (LARGE, time.monotonic() - 1)
        self.assertIsNone(runner_types.chosen("c1"))

    def test_use_keeps_only_the_same_size(self):
        runner_types.choose("c1", LARGE, 10)
        runner_types.keep("c1", LARGE, 1000)
        self.assertGreater(runner_types._choices["c1"][1], time.monotonic() + 500)
        runner_types.keep("c1", MEDIUM, 5000)
        self.assertEqual(runner_types.chosen("c1"), LARGE)
        self.assertLess(runner_types._choices["c1"][1], time.monotonic() + 2000)


class ClaimTest(IsolatedAsyncioTestCase):
    def tearDown(self):
        runner_types._choices.clear()

    def test_default_pool_keeps_the_plain_claim_name(self):
        self.assertEqual(k8s.claim_name("abc"), "runner-abc")
        self.assertEqual(k8s.claim_name("abc", LARGE), "runner-abc-large")
        long = k8s.claim_name("x" * 80, MEDIUM)
        self.assertLessEqual(len(long), 63)
        self.assertTrue(long.endswith("-medium"))

    async def test_a_sized_claim_uses_its_pool_label_and_idle_time(self):
        post = AsyncMock(return_value={})
        with patch(f"{K}._k8s", post):
            await k8s.create_claim("abc", LARGE)
        body = post.await_args.args[2]
        self.assertEqual(body["metadata"]["name"], "runner-abc-large")
        self.assertEqual(body["spec"]["warmPoolRef"]["name"], "weather-skills-large-runner")
        self.assertEqual(body["metadata"]["labels"][runner_types.CLAIM_TYPE_LABEL], "large")
        self.assertEqual(k8s._type_ttl(LARGE), 300)
        self.assertEqual(k8s._type_start_timeout(LARGE), 300)

    def test_waiting_line_names_a_cold_size(self):
        self.assertEqual(k8s.waiting_status(None), k8s.WAITING_STATUS)
        self.assertIn("Large", k8s.waiting_status(LARGE))
        self.assertIn("few minutes", k8s.waiting_status(LARGE))


class SwitchTest(IsolatedAsyncioTestCase):
    def setUp(self):
        k8s._ready_cache.clear()
        k8s._starts.clear()
        k8s._start_types.clear()
        k8s._watchers.clear()
        k8s._switched_chats.clear()

    def tearDown(self):
        runner_types._choices.clear()
        self.setUp()

    def test_switching_drops_the_remembered_runner_of_the_old_size(self):
        k8s._store_runner("c1", {"pod_name": "std", "pod_ip": "10.0.0.1", "rtype": None})
        self.assertIsNotNone(k8s._cached_runner("c1"))
        k8s.switch_runner_type("c1", LARGE, _catalog())
        self.assertEqual(k8s.current_runner_type("c1"), LARGE)
        self.assertIsNone(k8s._cached_runner("c1"))

    def test_switching_to_the_default_size_clears_the_choice(self):
        k8s.switch_runner_type("c1", MEDIUM, _catalog())
        k8s.switch_runner_type("c1", STANDARD, _catalog())
        self.assertIsNone(k8s.current_runner_type("c1"))
        self.assertEqual(k8s.effective_runner_type("c1", _catalog()), STANDARD)

    async def test_a_start_for_the_old_size_is_not_reused(self):
        gate = asyncio.Event()

        async def slow_start(chat_id):
            await gate.wait()
            return {}

        with patch(f"{K}._run_start", side_effect=slow_start):
            first = k8s.start_runner("c1")
            self.assertIs(k8s.start_runner("c1"), first)
            k8s.switch_runner_type("c1", MEDIUM, _catalog())
            second = k8s.start_runner("c1")
            self.assertIsNot(second, first)
            self.assertEqual(k8s._start_types["c1"], MEDIUM)
            gate.set()
            await asyncio.gather(first, second)

    async def test_release_deletes_idle_claims_of_other_sizes_only(self):
        k8s.switch_runner_type("c1", LARGE, _catalog())
        claims = [
            {"metadata": {"name": "runner-c1", "uid": "u-std"}, "status": {"sandbox": {"name": "std"}}},
            {"metadata": {"name": "runner-c1-medium", "uid": "u-med"}, "status": {"sandbox": {"name": "med"}}},
            {"metadata": {"name": "runner-c1-large", "uid": "u-big"}, "status": {"sandbox": {"name": "big"}}},
        ]
        # A call still running on the medium runner.
        k8s._watchers[("c1", "med")] = [None, 1, None]
        with patch(f"{K}.list_chat_claims", AsyncMock(return_value=claims)), patch(
            f"{K}._delete_claim_named", AsyncMock()
        ) as delete:
            await k8s.release_other_runners("c1")
        delete.assert_awaited_once_with("runner-c1", "u-std")

    async def test_the_last_call_on_an_old_size_releases_it(self):
        k8s.switch_runner_type("c1", LARGE, _catalog())
        old = {"pod_name": "std", "pod_ip": "10.0.0.1", "rtype": None}
        with patch(f"{K}._watch_runner", AsyncMock()), patch(
            f"{K}.release_other_runners", AsyncMock()
        ) as release:
            async with k8s._watching_runner("c1", old):
                release.assert_not_awaited()
            await asyncio.sleep(0)
        release.assert_awaited_once_with("c1")

    async def test_a_chat_never_switched_lists_no_claims(self):
        with patch(f"{K}.list_chat_claims", AsyncMock()) as listing:
            k8s._release_soon("c1")
            await asyncio.sleep(0)
        listing.assert_not_awaited()

    def test_oom_message_suggests_a_larger_size_when_there_is_one(self):
        k8s._catalog_cache = (time.monotonic(), 300, _catalog())
        try:
            self.assertIn("request_tool_runner", k8s._oom_message("", None))
            self.assertNotIn("request_tool_runner", k8s._oom_message("", LARGE))
        finally:
            k8s._catalog_cache = None

    async def test_guidance_lists_sizes_and_the_current_one(self):
        k8s.switch_runner_type("c1", MEDIUM, _catalog())
        with patch(f"{K}.runner_catalog", AsyncMock(return_value=_catalog())):
            text = await k8s.runner_sizes_guidance("c1", _catalog())
            self.assertIn("`large`", text)
            self.assertIn("needs the user's approval", text)
            self.assertIn("This chat is on `medium`", text)
            self.assertIsNone(await k8s.runner_sizes_guidance("c1", [STANDARD]))
        self.assertIn("16 GiB", await k8s.runner_resources_guidance("c1"))


class RequestToolRunnerTest(IsolatedAsyncioTestCase):
    def setUp(self):
        k8s._switched_chats.clear()

    def tearDown(self):
        runner_types._choices.clear()
        k8s._switched_chats.clear()

    async def _call(self, size, *, allowed=None, approve=True, headless=False, event_call=True):
        from open_webui.utils import builtin_tools

        asked = []

        async def confirm(event):
            asked.append(event)
            return approve

        access = SimpleNamespace(readable=True)
        metadata = {"chat_id": "c1", "organization_id": "org"}
        if headless:
            metadata["headless"] = True
        with patch.object(builtin_tools, "_chat_access", AsyncMock(return_value=access)), patch(
            f"{K}.runner_catalog", AsyncMock(return_value=_catalog())
        ), patch(
            f"{K}.runner_types_for_org", AsyncMock(return_value=allowed or _catalog())
        ), patch(f"{K}.start_runner") as start, patch(
            "open_webui.utils.chat_realtime.emit_chat_runner", AsyncMock()
        ), patch("open_webui.utils.chat_realtime.schedule_runner_metrics"):
            result = await builtin_tools.request_tool_runner(
                size,
                reason="ERA5 over Africa for 30 years",
                __user__={"id": "u1"},
                __metadata__=metadata,
                __event_call__=confirm if event_call else None,
            )
        return result, asked, start

    async def test_a_size_needing_approval_asks_the_user(self):
        result, asked, start = await self._call("large")
        self.assertEqual(len(asked), 1)
        self.assertEqual(asked[0]["type"], "confirmation")
        self.assertIn("Large", asked[0]["data"]["title"])
        self.assertIn("ERA5 over Africa", asked[0]["data"]["message"])
        self.assertIn("Switched this chat to the Large", result)
        self.assertEqual(k8s.current_runner_type("c1"), LARGE)
        start.assert_called_once_with("c1")

    async def test_declined_leaves_the_runner(self):
        result, asked, start = await self._call("large", approve=False)
        self.assertIn("declined", result)
        self.assertIsNone(k8s.current_runner_type("c1"))
        start.assert_not_called()

    async def test_a_size_without_approval_switches_without_asking(self):
        result, asked, _ = await self._call("medium")
        self.assertEqual(asked, [])
        self.assertEqual(k8s.current_runner_type("c1"), MEDIUM)

    async def test_going_smaller_never_asks(self):
        k8s.switch_runner_type("c1", LARGE, _catalog())
        result, asked, _ = await self._call("standard")
        self.assertEqual(asked, [])
        self.assertIsNone(k8s.current_runner_type("c1"))

    async def test_a_size_the_organization_cannot_use_is_refused(self):
        result, asked, start = await self._call("large", allowed=[STANDARD, MEDIUM])
        self.assertIn("cannot use Large", result)
        self.assertEqual(asked, [])
        start.assert_not_called()

    async def test_a_scheduled_run_cannot_ask(self):
        result, asked, _ = await self._call("large", headless=True)
        self.assertIn("scheduled task cannot", result)
        self.assertIsNone(k8s.current_runner_type("c1"))

    async def test_unknown_size_lists_the_choices(self):
        result, _, _ = await self._call("huge")
        self.assertIn("`standard`", result)
        self.assertIn("`large`", result)

    async def test_already_on_that_size(self):
        result, asked, start = await self._call("standard")
        self.assertIn("already", result)
        start.assert_not_called()
