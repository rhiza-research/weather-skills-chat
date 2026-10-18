from pathlib import Path
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

from open_webui.utils.skill_k8s_sandbox import (
    PACKS_ANN,
    RUNNER_HOLD_BUFFER_SEC,
    RUNNER_UV_CACHE_DIR,
    WAITING_STATUS,
    _runner_log_name,
    _http_failure,
    _http_json,
    _drop_runner,
    _emit_waiting,
    _ready_cache,
    _missing_packs,
    _pack_names,
    _latest_skill_packs,
    _runner_packs_root,
    _runner_workspace,
    _store_runner,
    _tar_pack,
    _uv_cache_dir,
    await_runner_for_chat,
    bind_workspace,
    claim_name,
    delete_claim,
    emulator_enabled,
    extend_claim_ttl,
    hold_runner_for_skill,
    in_cluster,
    remote_script_path,
    public_runner_state,
    RUNNER_DIED_MESSAGE,
    runner_hold_seconds,
    runner_needs_wait,
    runner_metrics,
    runner_ready,
    runner_status,
    run_skill_on_runner,
    start_runner,
    use_direct_http,
)


class RunnerLogNameTest(TestCase):
    def test_prefers_pod_name(self):
        self.assertEqual(
            _runner_log_name({"pod_name": "weather-skills-standard-runner-abc", "pod_ip": "10.0.0.1"}),
            "weather-skills-standard-runner-abc",
        )

    def test_falls_back_to_pod_ip(self):
        self.assertEqual(_runner_log_name({"pod_ip": "10.0.0.1"}), "10.0.0.1")

    def test_unknown_when_missing(self):
        self.assertEqual(_runner_log_name({}), "?")


class ClaimNameTest(TestCase):
    def test_strips_unsafe_characters(self):
        self.assertEqual(claim_name("abc_def"), "runner-abc-def")

    def test_truncates(self):
        name = claim_name("x" * 80)
        self.assertLessEqual(len(name), 63)
        self.assertTrue(name.startswith("runner-"))


class HttpFailureTest(TestCase):
    def test_empty_timeout_names_the_request(self):
        err = _http_failure("POST", "http://10.0.0.1:8888/exec", 30, TimeoutError())
        self.assertEqual(str(err), "POST http://10.0.0.1:8888/exec timed out after 30s")

    def test_empty_client_error_uses_type_name(self):
        class BlankDisconnect(Exception):
            def __str__(self):
                return ""

        err = _http_failure(
            "GET", "http://10.0.0.1:8888/health", 30, BlankDisconnect()
        )
        self.assertIn("BlankDisconnect", str(err))
        self.assertIn("/health", str(err))


class HttpJsonTimeoutTest(IsolatedAsyncioTestCase):
    async def test_timeout_becomes_runtime_error_with_url(self):
        class Boom:
            async def __aenter__(self):
                raise TimeoutError()

            async def __aexit__(self, *args):
                return False

        class Session:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            def request(self, *args, **kwargs):
                return Boom()

        with patch(
            "open_webui.utils.skill_k8s_sandbox.aiohttp.ClientSession", Session
        ):
            with self.assertRaises(RuntimeError) as ctx:
                await _http_json("POST", "http://10.0.0.1:8888/exec", timeout=30)
        self.assertEqual(
            str(ctx.exception), "POST http://10.0.0.1:8888/exec timed out after 30s"
        )


class TransportTest(TestCase):
    def test_laptop_is_not_in_cluster(self):
        self.assertFalse(in_cluster())
        self.assertFalse(use_direct_http())

    def test_tunnel_flag_forces_port_forward(self):
        with patch(
            "open_webui.utils.skill_k8s_sandbox.in_cluster", return_value=True
        ), patch.dict("os.environ", {"SKILL_K8S_TUNNEL": "1"}):
            self.assertFalse(use_direct_http())

    def test_emulator_uses_direct_http(self):
        with patch.dict("os.environ", {"SKILL_K8S_EMULATOR": "1"}, clear=False):
            self.assertTrue(emulator_enabled())
            self.assertTrue(use_direct_http())

    def test_emulator_workspace_is_runner_workspace(self):
        with patch.dict(
            "os.environ",
            {
                "SKILL_K8S_EMULATOR": "1",
                "ARTIFACTS_DIR": "/app/backend/data/artifacts",
            },
            clear=False,
        ):
            self.assertEqual(
                _runner_workspace("21f8fc6d-f50a-4875-8c8d-bade664d2054"),
                "/workspace/chat",
            )
            self.assertEqual(_uv_cache_dir("/workspace/chat"), RUNNER_UV_CACHE_DIR)
            self.assertEqual(RUNNER_UV_CACHE_DIR, "/opt/uv-cache")

    def test_runner_uv_cache_override(self):
        with patch.dict("os.environ", {"SKILL_K8S_UV_CACHE_DIR": "/tmp/uv-cache"}, clear=False):
            self.assertEqual(_uv_cache_dir("/workspace/chat"), "/tmp/uv-cache")


class RemoteScriptPathTest(TestCase):
    def test_pack_at_skills_root(self):
        with patch.dict("os.environ", {"SKILLS_DIR": "/data/skills"}):
            path = remote_script_path(
                Path("/data/skills/probe-skill"),
                Path("/data/skills/probe-skill/scripts/probe_skill.py"),
            )
        self.assertEqual(
            path, "/workspace/.skill-packs/probe-skill/scripts/probe_skill.py"
        )

    def test_nested_skill_dir(self):
        with patch.dict("os.environ", {"SKILLS_DIR": "/data/skills"}):
            path = remote_script_path(
                Path("/data/skills/pack/skills/inner"),
                Path("/data/skills/pack/skills/inner/scripts/main.py"),
            )
        self.assertEqual(
            path, "/workspace/.skill-packs/pack/skills/inner/scripts/main.py"
        )

    def test_packs_live_beside_the_chat_workspace(self):
        self.assertEqual(_runner_packs_root(), "/workspace/.skill-packs")

    def test_tar_pack_skips_cache_dirs(self):
        import io
        import tarfile
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "pack"
            (root / "scripts").mkdir(parents=True)
            (root / "scripts" / "run.py").write_text("print(1)\n")
            cache = root / "__pycache__"
            cache.mkdir()
            (cache / "run.pyc").write_text("x")
            archive = _tar_pack(root)
        names = tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz").getnames()
        self.assertIn("pack/scripts/run.py", names)
        self.assertFalse(any("__pycache__" in name for name in names))

    def test_missing_packs_ignores_ones_already_present(self):
        wanted = [Path("/data/skills/weather-skills"), Path("/data/skills/plotting")]
        self.assertEqual(_pack_names(wanted), {"weather-skills", "plotting"})
        self.assertEqual(
            [p.name for p in _missing_packs({"weather-skills"}, wanted)],
            ["plotting"],
        )
        self.assertEqual(
            [p.name for p in _missing_packs({"weather-skills", "plotting"}, wanted)],
            [],
        )

    def test_latest_skill_packs_keeps_the_newest_version(self):
        import tempfile
        from types import SimpleNamespace

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old_skill = root / "plotting-old" / "skills" / "plot"
            new_skill = root / "plotting-new" / "skills" / "plot"
            old_skill.mkdir(parents=True)
            new_skill.mkdir(parents=True)
            old = SimpleNamespace(
                id="plot-old",
                meta=SimpleNamespace(manifest={"skill_dir": str(old_skill)}),
            )
            new = SimpleNamespace(
                id="plot-new",
                meta=SimpleNamespace(manifest={"skill_dir": str(new_skill)}),
            )
            records = [
                {
                    "id": "plot-old",
                    "skill_name": "plot",
                    "version": "0.1.0",
                    "enabled": True,
                },
                {
                    "id": "plot-new",
                    "skill_name": "plot",
                    "version": "0.2.0",
                    "enabled": True,
                },
                {
                    "id": "plot-off",
                    "skill_name": "plot",
                    "version": "9.0.0",
                    "enabled": False,
                },
            ]
            with patch.dict("os.environ", {"SKILLS_DIR": str(root)}, clear=False):
                packs = _latest_skill_packs(records, [old, new])
        self.assertEqual([p.name for p in packs], ["plotting-new"])


class RunnerNeedsWaitTest(TestCase):
    def test_no_claim_waits(self):
        self.assertTrue(runner_needs_wait(None))

    def test_starting_claim_waits(self):
        self.assertTrue(
            runner_needs_wait({"status": {"ready": False, "conditions": []}})
        )

    def test_ready_without_pod_waits(self):
        self.assertTrue(runner_needs_wait({"status": {"ready": True}}))

    def test_ready_with_pod_does_not_wait(self):
        self.assertFalse(
            runner_needs_wait(
                {"status": {"ready": True, "sandbox": {"name": "runner-1"}}}
            )
        )

    def test_waiting_status_copy(self):
        self.assertEqual(WAITING_STATUS, "Waiting on weather skills runner")


class EmitWaitingTest(IsolatedAsyncioTestCase):
    async def test_visible_while_waiting(self):
        events = []

        async def emitter(event):
            events.append(event)

        await _emit_waiting(emitter, False)
        self.assertEqual(
            events[0]["data"],
            {
                "action": "weather_skills_runner",
                "description": WAITING_STATUS,
                "done": False,
            },
        )

    async def test_hides_when_runner_is_ready(self):
        events = []

        async def emitter(event):
            events.append(event)

        await _emit_waiting(emitter, True)
        self.assertTrue(events[0]["data"]["hidden"])
        self.assertTrue(events[0]["data"]["done"])


class AwaitRunnerForChatTest(IsolatedAsyncioTestCase):
    def tearDown(self):
        _drop_runner("chat-1")

    async def test_skips_when_runner_path_is_off(self):
        with patch.dict(
            "os.environ",
            {"SKILL_SANDBOX_BACKEND": "landlock", "SKILL_K8S_SANDBOX_ENABLED": "false"},
            clear=False,
        ), patch("open_webui.utils.skill_k8s_sandbox.start_runner") as start:
            await await_runner_for_chat("chat-1")
            start.assert_not_called()

    async def test_skips_temporary_chat(self):
        with patch.dict(
            "os.environ",
            {"SKILL_SANDBOX_BACKEND": "k8s", "SKILL_K8S_SANDBOX_ENABLED": "true"},
            clear=False,
        ), patch("open_webui.utils.skill_k8s_sandbox.start_runner") as start:
            await await_runner_for_chat("local")
            await await_runner_for_chat(None)
            start.assert_not_called()

    async def test_ready_runner_does_not_show_waiting(self):
        events = []

        async def emitter(event):
            events.append(event)

        _store_runner("chat-1", {"pod_ip": "10.0.0.1"})
        with patch.dict(
            "os.environ",
            {"SKILL_SANDBOX_BACKEND": "k8s", "SKILL_K8S_SANDBOX_ENABLED": "true"},
            clear=False,
        ), patch("open_webui.utils.skill_k8s_sandbox.start_runner") as start, patch(
            "open_webui.utils.skill_k8s_sandbox.runner_status"
        ) as status:
            await await_runner_for_chat("chat-1", emitter=emitter)
            start.assert_not_called()
            status.assert_not_called()
        self.assertEqual(events, [])
        self.assertTrue(runner_ready("chat-1"))

    async def test_shows_waiting_until_start_finishes(self):
        import asyncio

        events = []
        finish = asyncio.Event()

        async def emitter(event):
            events.append(event)

        async def body():
            await finish.wait()
            return {"pod_ip": "10.0.0.1"}

        task = asyncio.create_task(body())
        with patch.dict(
            "os.environ",
            {"SKILL_SANDBOX_BACKEND": "k8s", "SKILL_K8S_SANDBOX_ENABLED": "true"},
            clear=False,
        ), patch(
            "open_webui.utils.skill_k8s_sandbox.start_runner", return_value=task
        ), patch(
            "open_webui.utils.skill_k8s_sandbox.runner_status"
        ) as status:
            wait = asyncio.create_task(await_runner_for_chat("chat-1", emitter=emitter))
            for _ in range(20):
                if events:
                    break
                await asyncio.sleep(0)
            self.assertTrue(events)
            self.assertEqual(events[0]["data"]["description"], WAITING_STATUS)
            self.assertFalse(events[0]["data"]["done"])
            status.assert_not_called()
            finish.set()
            await wait
        self.assertFalse(events[-1]["data"]["done"])


class DeleteClaimTest(IsolatedAsyncioTestCase):
    async def test_missing_claim_is_ok(self):
        with patch(
            "open_webui.utils.skill_k8s_sandbox._k8s",
            side_effect=RuntimeError("k8s DELETE ... -> 404: b''"),
        ):
            await delete_claim("missing")


class StartRunnerTest(IsolatedAsyncioTestCase):
    def tearDown(self):
        _drop_runner("chat-1")

    async def test_second_caller_shares_the_same_start(self):
        import asyncio

        gate = asyncio.Event()
        runs = {"n": 0}

        async def body(chat_id):
            runs["n"] += 1
            await gate.wait()
            return {"pod_ip": "10.0.0.1"}

        with patch(
            "open_webui.utils.skill_k8s_sandbox._run_start", side_effect=body
        ):
            first = start_runner("chat-1")
            second = start_runner("chat-1")
            self.assertIs(first, second)
            gate.set()
            await first
        self.assertEqual(runs["n"], 1)

    async def test_starts_again_after_the_ready_cache_expires(self):
        runs = {"n": 0}

        async def body(chat_id):
            runs["n"] += 1
            return {"pod_ip": "10.0.0.1"}

        with patch(
            "open_webui.utils.skill_k8s_sandbox._run_start", side_effect=body
        ):
            first = start_runner("chat-1")
            await first
            _store_runner("chat-1", {"pod_ip": "10.0.0.1"})
            self.assertIs(start_runner("chat-1"), first)
            _ready_cache.pop("chat-1", None)
            second = start_runner("chat-1")
            self.assertIsNot(second, first)
            await second
        self.assertEqual(runs["n"], 2)

    async def test_does_not_start_again_while_the_runner_is_still_remembered(self):
        clock = {"t": 1000.0}

        async def body(chat_id):
            return {"pod_ip": "10.0.0.1"}

        with patch(
            "open_webui.utils.skill_k8s_sandbox.time.monotonic",
            side_effect=lambda: clock["t"],
        ), patch(
            "open_webui.utils.skill_k8s_sandbox._run_start", side_effect=body
        ):
            first = start_runner("chat-1")
            await first
            _store_runner("chat-1", {"pod_ip": "10.0.0.1"})
            clock["t"] += 20.0
            self.assertIs(start_runner("chat-1"), first)


class RunnerStatusTest(IsolatedAsyncioTestCase):
    def setUp(self):
        _drop_runner("chat-1")

    def tearDown(self):
        _drop_runner("chat-1")

    async def test_cache_is_ready_without_another_pack_check(self):
        _store_runner("chat-1", {"pod_ip": "10.0.0.1"})
        with patch("open_webui.utils.skill_k8s_sandbox.get_claim") as get_claim, patch(
            "open_webui.utils.skill_k8s_sandbox._runner_health",
            new_callable=AsyncMock,
            return_value="ok",
        ):
            status = await runner_status("chat-1")
        self.assertEqual(status["state"], "ready")
        get_claim.assert_not_called()

    async def test_dead_cached_runner_is_paused(self):
        _store_runner("chat-1", {"pod_ip": "10.0.0.1"})
        with patch(
            "open_webui.utils.skill_k8s_sandbox._runner_health",
            new_callable=AsyncMock,
            return_value="unhealthy",
        ), patch(
            "open_webui.utils.skill_k8s_sandbox.get_claim",
            new_callable=AsyncMock,
            return_value=None,
        ):
            status = await runner_status("chat-1")
        self.assertEqual(status["state"], "absent")
        self.assertIsNone(_ready_cache.get("chat-1"))

    async def test_ready_when_runner_lists_installed_packs(self):
        claim = {
            "status": {"ready": True, "sandbox": {"name": "runner-1"}},
        }
        pod = {
            "metadata": {"name": "runner-1", "annotations": {}},
            "status": {"podIP": "10.0.0.8"},
        }
        with patch(
            "open_webui.utils.skill_k8s_sandbox.get_claim", return_value=claim
        ), patch(
            "open_webui.utils.skill_k8s_sandbox.get_pod", return_value=pod
        ), patch(
            "open_webui.utils.skill_k8s_sandbox._runner_health",
            new_callable=AsyncMock,
            return_value="ok",
        ), patch(
            "open_webui.utils.skill_k8s_sandbox._listed_packs",
            return_value={"weather-skills"},
        ), patch(
            "open_webui.utils.skill_k8s_sandbox._packs_for_chat",
            return_value=[Path("/data/skills/weather-skills")],
        ):
            status = await runner_status("chat-1")
        self.assertEqual(status["state"], "ready")
        self.assertIsNotNone(_ready_cache.get("chat-1"))

    async def test_pod_marked_ready_does_not_list_packs(self):
        claim = {
            "status": {"ready": True, "sandbox": {"name": "runner-1"}},
        }
        pod = {
            "metadata": {
                "name": "runner-1",
                "annotations": {PACKS_ANN: "ready"},
            },
            "status": {"podIP": "10.0.0.8"},
        }
        with patch(
            "open_webui.utils.skill_k8s_sandbox.get_claim", return_value=claim
        ), patch(
            "open_webui.utils.skill_k8s_sandbox.get_pod", return_value=pod
        ), patch(
            "open_webui.utils.skill_k8s_sandbox._runner_health",
            new_callable=AsyncMock,
            return_value="ok",
        ), patch(
            "open_webui.utils.skill_k8s_sandbox._listed_packs"
        ) as listed:
            status = await runner_status("chat-1")
        listed.assert_not_called()
        self.assertEqual(status["state"], "ready")
        self.assertIsNotNone(_ready_cache.get("chat-1"))

    async def test_starting_when_packs_are_missing(self):
        claim = {
            "status": {"ready": True, "sandbox": {"name": "runner-1"}},
        }
        pod = {
            "metadata": {"name": "runner-1", "annotations": {}},
            "status": {"podIP": "10.0.0.8"},
        }
        with patch(
            "open_webui.utils.skill_k8s_sandbox.get_claim", return_value=claim
        ), patch(
            "open_webui.utils.skill_k8s_sandbox.get_pod", return_value=pod
        ), patch(
            "open_webui.utils.skill_k8s_sandbox._runner_health",
            new_callable=AsyncMock,
            return_value="ok",
        ), patch(
            "open_webui.utils.skill_k8s_sandbox._listed_packs",
            return_value=set(),
        ), patch(
            "open_webui.utils.skill_k8s_sandbox._packs_for_chat",
            return_value=[Path("/data/skills/weather-skills")],
        ):
            status = await runner_status("chat-1")
        self.assertEqual(status["state"], "starting")


class PublicRunnerStateTest(TestCase):
    def test_maps_absent_to_paused(self):
        self.assertEqual(public_runner_state("absent"), "paused")
        self.assertEqual(public_runner_state(None), "paused")

    def test_keeps_starting_and_ready(self):
        self.assertEqual(public_runner_state("starting"), "starting")
        self.assertEqual(public_runner_state("ready"), "ready")


class RunnerHoldTest(TestCase):
    def test_short_skill_keeps_the_idle_ttl(self):
        with patch(
            "open_webui.utils.skill_k8s_sandbox._ttl_seconds", return_value=600
        ):
            self.assertEqual(runner_hold_seconds(30), 600)

    def test_long_skill_holds_past_its_timeout(self):
        with patch(
            "open_webui.utils.skill_k8s_sandbox._ttl_seconds", return_value=600
        ):
            self.assertEqual(
                runner_hold_seconds(600), 600 + RUNNER_HOLD_BUFFER_SEC
            )
            self.assertEqual(
                runner_hold_seconds(900), 900 + RUNNER_HOLD_BUFFER_SEC
            )


class HoldRunnerForSkillTest(IsolatedAsyncioTestCase):
    async def test_cached_runner_still_extends_the_claim(self):
        claim = {
            "metadata": {"name": "runner-chat-1"},
            "spec": {"lifecycle": {"shutdownTime": "2026-10-14T19:26:05Z"}},
        }
        holds = []

        async def get(chat_id):
            return claim

        async def extend(body, seconds=None):
            holds.append(seconds)
            return body

        with patch(
            "open_webui.utils.skill_k8s_sandbox._ttl_seconds", return_value=600
        ), patch(
            "open_webui.utils.skill_k8s_sandbox.get_claim", side_effect=get
        ), patch(
            "open_webui.utils.skill_k8s_sandbox.extend_claim_ttl", side_effect=extend
        ):
            await hold_runner_for_skill("chat-1", 600)
        self.assertEqual(holds, [600 + RUNNER_HOLD_BUFFER_SEC])

    async def test_run_skill_holds_even_when_the_runner_is_already_ready(self):
        holds = []

        async def ensure(chat_id, *, emitter=None):
            info = {"pod_ip": "10.0.0.1", "pod_name": "ready"}
            _store_runner(chat_id, info)
            return info

        async def exec_on(chat_id, argv, **kwargs):
            return {"exit_code": 0, "stdout": "ok", "stderr": ""}

        async def hold(chat_id, timeout):
            holds.append(timeout)

        with patch(
            "open_webui.utils.skill_k8s_sandbox.ensure_runner", side_effect=ensure
        ), patch(
            "open_webui.utils.skill_k8s_sandbox.exec_on_runner", side_effect=exec_on
        ), patch(
            "open_webui.utils.skill_k8s_sandbox.hold_runner_for_skill", side_effect=hold
        ), patch(
            "open_webui.utils.skill_k8s_sandbox.remote_script_path",
            return_value="/workspace/.skill-packs/x/script.py",
        ):
            await run_skill_on_runner(
                chat_id="chat-1",
                skill_dir=Path("/data/skills/x"),
                script_path=Path("/data/skills/x/script.py"),
                args=[],
                env={},
                timeout=600,
            )
        _drop_runner("chat-1")
        self.assertEqual(holds, [600])

    async def test_extend_claim_ttl_uses_the_requested_hold(self):
        puts = []

        async def k8s(method, path, body=None, timeout=30):
            puts.append((method, path, body))
            return body or {}

        claim = {
            "metadata": {"name": "runner-chat-1"},
            "spec": {"lifecycle": {}},
        }
        with patch(
            "open_webui.utils.skill_k8s_sandbox._k8s", side_effect=k8s
        ), patch(
            "open_webui.utils.skill_k8s_sandbox.datetime"
        ) as dt:
            from datetime import datetime, timezone

            dt.now.return_value = datetime(2026, 10, 14, 19, 16, 5, tzinfo=timezone.utc)
            await extend_claim_ttl(claim, seconds=660)
        self.assertEqual(puts[0][0], "PUT")
        self.assertEqual(
            puts[0][2]["spec"]["lifecycle"]["shutdownTime"],
            "2026-10-14T19:27:05Z",
        )


class RecoverBrokenRunnerTest(IsolatedAsyncioTestCase):
    def tearDown(self):
        _drop_runner("chat-1")

    async def test_a_lost_exec_tells_the_user_to_retry(self):
        info = {"pod_ip": "10.0.0.1", "pod_name": "old", "claim": {"metadata": {"uid": "claim-old"}}}
        execs = []

        async def ensure(chat_id, *, emitter=None):
            _store_runner(chat_id, info)
            return info

        async def exec_on(chat_id, argv, **kwargs):
            execs.append(kwargs.get("info"))
            raise RuntimeError("POST http://10.0.0.1:8888/exec -> 502")

        with patch(
            "open_webui.utils.skill_k8s_sandbox.ensure_runner", side_effect=ensure
        ), patch(
            "open_webui.utils.skill_k8s_sandbox.exec_on_runner", side_effect=exec_on
        ), patch(
            "open_webui.utils.skill_k8s_sandbox.delete_claim"
        ) as delete, patch(
            "open_webui.utils.skill_k8s_sandbox.get_pod",
            side_effect=RuntimeError("404"),
        ), patch(
            "open_webui.utils.skill_k8s_sandbox._runner_health",
            AsyncMock(return_value="no_answer"),
        ), patch(
            "open_webui.utils.skill_k8s_sandbox.remote_script_path",
            return_value="/workspace/.skill-packs/x/script.py",
        ), self.assertLogs(
            "open_webui.utils.skill_k8s_sandbox", level="INFO"
        ) as logs:
            result = await run_skill_on_runner(
                chat_id="chat-1",
                skill_dir=Path("/data/skills/x"),
                script_path=Path("/data/skills/x/script.py"),
                args=[],
                env={},
                timeout=30,
            )
        self.assertFalse(result["ok"])
        # The pod is gone, so the runner died. Nothing is deleted here: the
        # readiness check or the next tool call's /health check replaces it.
        self.assertEqual(result["stderr"], RUNNER_DIED_MESSAGE)
        delete.assert_not_awaited()
        self.assertEqual(len(execs), 1)
        text = "\n".join(logs.output)
        self.assertIn("skill exec start chat=chat-1 script=script.py runner=old", text)
        self.assertIn("tool runner unreachable chat=chat-1 runner=old", text)
        self.assertNotIn("skill exec retry", text)

    async def test_failed_metrics_forget_a_ready_runner(self):
        _store_runner("chat-1", {"pod_ip": "10.0.0.1"})
        with patch(
            "open_webui.utils.skill_k8s_sandbox.get_claim",
            side_effect=RuntimeError("404"),
        ):
            with self.assertRaises(RuntimeError):
                await runner_metrics("chat-1")
        self.assertIsNone(_ready_cache.get("chat-1"))

    async def test_start_after_drop_is_a_new_runner(self):
        runs = {"n": 0}

        async def body(chat_id):
            runs["n"] += 1
            info = {"pod_ip": f"10.0.0.{runs['n']}"}
            _store_runner(chat_id, info)
            return info

        with patch(
            "open_webui.utils.skill_k8s_sandbox._run_start", side_effect=body
        ):
            first = start_runner("chat-1")
            await first
            _drop_runner("chat-1")
            second = start_runner("chat-1")
            self.assertIsNot(second, first)
            await second
        self.assertEqual(runs["n"], 2)


class BindWorkspaceTest(IsolatedAsyncioTestCase):
    async def test_owns_intermediate_results_folder_then_binds(self):
        calls = []

        async def http(method, url, **kwargs):
            calls.append((method, url, kwargs.get("json_body")))
            return {"ok": True}

        with patch(
            "open_webui.utils.skill_k8s_sandbox._bind_base",
            new_callable=AsyncMock,
            return_value="http://10.0.0.9:9090",
        ), patch(
            "open_webui.utils.skill_k8s_sandbox.bind_token",
            new_callable=AsyncMock,
            return_value="tok",
        ), patch(
            "open_webui.utils.skill_k8s_sandbox._quota_gib",
            return_value=200,
        ), patch(
            "open_webui.utils.skill_k8s_sandbox._http_json",
            side_effect=http,
        ):
            await bind_workspace("chat-1", {"metadata": {"uid": "pod-uid"}})

        paths = [url.rsplit("/", 1)[-1] for _method, url, _body in calls]
        self.assertEqual(paths, ["quota", "own", "bind"])
        self.assertEqual(calls[1][2]["chat_id"], "chat-1")
        self.assertEqual(calls[1][2]["paths"], ["intermediate_results"])
        self.assertEqual(calls[1][2]["trees"], [])
        self.assertEqual(calls[2][2], {"chat_id": "chat-1", "pod_uid": "pod-uid"})

    async def test_own_workspace_can_walk_trees(self):
        from open_webui.utils.skill_k8s_sandbox import own_workspace

        calls = []

        async def http(method, url, **kwargs):
            calls.append((url, kwargs.get("json_body")))
            return {"ok": True}

        with patch(
            "open_webui.utils.skill_k8s_sandbox._bind_base",
            new_callable=AsyncMock,
            return_value="http://10.0.0.9:9090",
        ), patch(
            "open_webui.utils.skill_k8s_sandbox.bind_token",
            new_callable=AsyncMock,
            return_value="tok",
        ), patch(
            "open_webui.utils.skill_k8s_sandbox._http_json",
            side_effect=http,
        ):
            await own_workspace(
                "chat-1",
                {"metadata": {"uid": "pod-uid"}},
                paths=["notes.csv"],
                trees=["plots"],
            )
            await own_workspace("chat-1", {"metadata": {"uid": "pod-uid"}})

        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0][0].endswith("/own"))
        self.assertEqual(calls[0][1]["paths"], ["notes.csv"])
        self.assertEqual(calls[0][1]["trees"], ["plots"])


def _runner(pod_name: str, uid: str) -> dict:
    return {"pod_ip": "10.0.0.1", "pod_name": pod_name, "claim": {"metadata": {"uid": uid}}}


class RunnerFaultTest(IsolatedAsyncioTestCase):
    """A tool call that fails because of the runner gets a clear error; nothing is deleted."""

    def tearDown(self):
        _drop_runner("chat-1")

    async def _run(self, info, *, exec_result=None, exec_error=None, pod=None, health="ok"):
        async def ensure(chat_id, *, emitter=None):
            _store_runner(chat_id, info)
            return info

        async def exec_on(chat_id, argv, **kwargs):
            if exec_error:
                raise exec_error
            return exec_result

        pod_mock = AsyncMock(return_value=pod) if pod is not None else AsyncMock(side_effect=RuntimeError("404"))
        with patch("open_webui.utils.skill_k8s_sandbox.ensure_runner", side_effect=ensure), patch(
            "open_webui.utils.skill_k8s_sandbox.exec_on_runner", side_effect=exec_on
        ), patch("open_webui.utils.skill_k8s_sandbox.hold_runner_for_skill", AsyncMock()), patch(
            "open_webui.utils.skill_k8s_sandbox.get_pod", pod_mock
        ), patch(
            "open_webui.utils.skill_k8s_sandbox._runner_health", AsyncMock(return_value=health)
        ), patch(
            "open_webui.utils.skill_k8s_sandbox.delete_claim", AsyncMock()
        ) as delete, patch(
            "open_webui.utils.skill_k8s_sandbox.remote_script_path",
            return_value="/workspace/.skill-packs/x/script.py",
        ):
            result = await run_skill_on_runner(
                chat_id="chat-1",
                skill_dir=Path("/data/skills/x"),
                script_path=Path("/data/skills/x/script.py"),
                args=[],
                env={},
                timeout=30,
            )
        return result, delete

    async def test_oom_killed_runner_says_it_ran_out_of_memory(self):
        pod = {"status": {"containerStatuses": [{"lastState": {"terminated": {"reason": "OOMKilled"}}}]}}
        result, delete = await self._run(
            _runner("old", "u1"), exec_error=RuntimeError("connection reset"), pod=pod, health="no_answer"
        )
        self.assertFalse(result["ok"])
        self.assertIn("ran out of memory (OOMKilled)", result["stderr"])
        self.assertTrue(result["stderr"].startswith("Tool call failed:"))
        delete.assert_not_awaited()

    async def test_memory_eviction_says_it_ran_out_of_memory(self):
        pod = {"status": {"reason": "Evicted", "message": "The node was low on resource: memory."}}
        result, _ = await self._run(_runner("old", "u1"), exec_error=RuntimeError("reset"), pod=pod, health="no_answer")
        self.assertIn("ran out of memory (evicted: The node was low on resource: memory.)", result["stderr"])

    async def test_failed_skill_on_an_unhealthy_runner_replaces_it(self):
        result, delete = await self._run(
            _runner("old", "u1"),
            exec_result={"exit_code": 1, "stderr": "Transport endpoint is not connected"},
            health="unhealthy",
        )
        # An explicit 503 is definitive: delete that claim now.
        self.assertEqual(result["stderr"], RUNNER_DIED_MESSAGE)
        delete.assert_awaited_once_with("chat-1", uid="u1")
        self.assertIsNone(_ready_cache.get("chat-1"))

    async def test_failed_skill_on_a_healthy_runner_is_the_skills_failure(self):
        result, delete = await self._run(
            _runner("old", "u1"),
            exec_result={"exit_code": 2, "stdout": "", "stderr": "bad argument"},
            health="ok",
        )
        self.assertEqual(result["stderr"], "bad argument")
        self.assertEqual(result["exit_code"], 2)
        delete.assert_not_awaited()
        self.assertIsNotNone(_ready_cache.get("chat-1"))

    async def test_lost_exec_on_a_running_pod_says_it_may_be_overloaded(self):
        from open_webui.utils.skill_k8s_sandbox import RUNNER_UNREACHABLE_MESSAGE

        pod = {"status": {"phase": "Running", "containerStatuses": [{"name": "runner", "state": {"running": {}}}]}}
        result, delete = await self._run(
            _runner("old", "u1"), exec_error=RuntimeError("Connection reset by peer"), pod=pod, health="no_answer"
        )
        self.assertEqual(result["stderr"], RUNNER_UNREACHABLE_MESSAGE)
        delete.assert_not_awaited()
        self.assertIsNotNone(_ready_cache.get("chat-1"))

    async def test_lost_exec_on_a_terminated_runner_says_it_died(self):
        pod = {"status": {"phase": "Running", "containerStatuses": [{"name": "runner", "state": {"terminated": {"reason": "Error"}}}]}}
        result, delete = await self._run(_runner("old", "u1"), exec_error=RuntimeError("reset"), pod=pod, health="no_answer")
        self.assertEqual(result["stderr"], RUNNER_DIED_MESSAGE)
        delete.assert_not_awaited()

    async def test_lost_exec_on_a_runner_answering_503_deletes_its_claim(self):
        pod = {"status": {"phase": "Running", "containerStatuses": [{"name": "runner", "state": {"running": {}}}]}}
        result, delete = await self._run(_runner("old", "u1"), exec_error=RuntimeError("reset"), pod=pod, health="unhealthy")
        self.assertEqual(result["stderr"], RUNNER_DIED_MESSAGE)
        delete.assert_awaited_once_with("chat-1", uid="u1")

    async def test_failed_skill_with_a_slow_health_answer_is_the_skills_failure(self):
        result, delete = await self._run(
            _runner("old", "u1"),
            exec_result={"exit_code": 1, "stdout": "", "stderr": "ValueError: bad bbox"},
            health="no_answer",
        )
        self.assertEqual(result["stderr"], "ValueError: bad bbox")
        delete.assert_not_awaited()


class RunnerAliveTest(IsolatedAsyncioTestCase):
    """Only a 503, or Kubernetes saying the pod is gone or not Ready, condemns a runner."""

    async def _alive(self, health, pod=None, pod_error=None):
        from open_webui.utils.skill_k8s_sandbox import _runner_alive

        get_pod = AsyncMock(side_effect=pod_error) if pod_error else AsyncMock(return_value=pod)
        with patch("open_webui.utils.skill_k8s_sandbox._runner_health", AsyncMock(return_value=health)), patch(
            "open_webui.utils.skill_k8s_sandbox.get_pod", get_pod
        ):
            return await _runner_alive(_runner("p", "u1"))

    def _pod(self, ready: bool) -> dict:
        return {"status": {"phase": "Running", "conditions": [{"type": "Ready", "status": "True" if ready else "False"}]}}

    async def test_ok_is_alive(self):
        self.assertTrue(await self._alive("ok"))

    async def test_503_is_dead(self):
        self.assertFalse(await self._alive("unhealthy", pod=self._pod(True)))

    async def test_slow_answer_on_a_ready_pod_is_kept(self):
        self.assertTrue(await self._alive("no_answer", pod=self._pod(True)))

    async def test_slow_answer_on_a_not_ready_pod_is_dead(self):
        self.assertFalse(await self._alive("no_answer", pod=self._pod(False)))

    async def test_slow_answer_on_a_gone_pod_is_dead(self):
        self.assertFalse(await self._alive("no_answer", pod_error=RuntimeError("k8s GET ... -> 404: NotFound")))

    async def test_an_api_hiccup_is_not_a_verdict(self):
        self.assertTrue(await self._alive("no_answer", pod_error=RuntimeError("k8s GET ... timed out")))


class DeleteClaimPreconditionTest(IsolatedAsyncioTestCase):
    async def test_uid_is_sent_as_a_precondition(self):
        with patch("open_webui.utils.skill_k8s_sandbox._k8s", AsyncMock(return_value={})) as k8s:
            await delete_claim("chat-1", uid="u1")
        body = k8s.await_args.args[2]
        self.assertEqual(body["preconditions"], {"uid": "u1"})

    async def test_a_newer_claim_is_left_alone(self):
        conflict = RuntimeError("k8s DELETE ... -> 409: Precondition failed: UID in precondition")
        with patch("open_webui.utils.skill_k8s_sandbox._k8s", AsyncMock(side_effect=conflict)):
            await delete_claim("chat-1", uid="u1")


class StartPhaseTest(IsolatedAsyncioTestCase):
    """Claimed, bound, and packs unpacked; each step backs off inside one time limit."""

    def setUp(self):
        from open_webui.utils import skill_k8s_sandbox as k8s

        self.k8s = k8s
        k8s._starts.clear()
        k8s._start_failed_at.clear()
        _drop_runner("chat-1")
        self.claim = {"metadata": {"uid": "u1"}, "status": {"ready": True, "sandbox": {"name": "pod-1"}}}
        self.pod = {"metadata": {"annotations": {}}, "status": {"podIP": "10.0.0.1"}}

    def tearDown(self):
        self.k8s._starts.clear()
        self.k8s._start_failed_at.clear()
        _drop_runner("chat-1")

    def _patches(self, *, bind, timeout=60, get_claim=None, create=None):
        k = "open_webui.utils.skill_k8s_sandbox"
        return [
            patch(f"{k}._start_timeout_seconds", return_value=timeout),
            patch(f"{k}.get_claim", get_claim or AsyncMock(return_value=None)),
            patch(f"{k}.create_claim", create or AsyncMock(return_value=self.claim)),
            patch(f"{k}.wait_ready", AsyncMock(return_value=self.claim)),
            patch(f"{k}.get_pod", AsyncMock(return_value=self.pod)),
            patch(f"{k}.bind_workspace", bind),
            patch(f"{k}._annotate_pod", AsyncMock()),
            patch(f"{k}.verify_runtime", AsyncMock(return_value={})),
            patch(f"{k}._packs_ready_on_runner", AsyncMock(return_value=True)),
        ]

    async def _start(self, patches):
        for p in patches:
            p.start()
        try:
            return await self.k8s._run_start("chat-1")
        finally:
            for p in reversed(patches):
                p.stop()

    async def test_bind_backs_off_until_the_daemon_answers(self):
        bind = AsyncMock(side_effect=[RuntimeError("connection refused"), RuntimeError("connection refused"), None])
        info = await self._start(self._patches(bind=bind))
        self.assertEqual(bind.await_count, 3)
        self.assertEqual(info["pod_name"], "pod-1")
        self.assertIsNotNone(_ready_cache.get("chat-1"))

    async def test_gives_up_with_one_clear_error_after_the_time_limit(self):
        from open_webui.utils.skill_k8s_sandbox import RUNNER_UNAVAILABLE_MESSAGE, RunnerUnavailableError

        bind = AsyncMock(side_effect=RuntimeError("connection refused"))
        with self.assertRaises(RunnerUnavailableError) as ctx:
            await self._start(self._patches(bind=bind, timeout=1))
        self.assertEqual(str(ctx.exception), RUNNER_UNAVAILABLE_MESSAGE)
        self.assertIsNone(_ready_cache.get("chat-1"))

    async def test_waits_for_the_old_claim_to_go_before_claiming(self):
        deleting = {"metadata": {"uid": "u0", "deletionTimestamp": "2026-10-18T00:00:00Z"}}
        get_claim = AsyncMock(side_effect=[deleting, deleting, None])
        create = AsyncMock(return_value=self.claim)
        await self._start(self._patches(bind=AsyncMock(), get_claim=get_claim, create=create))
        self.assertEqual(get_claim.await_count, 3)
        create.assert_awaited_once()

    async def test_a_start_that_just_failed_is_reused(self):
        from open_webui.utils.skill_k8s_sandbox import RunnerUnavailableError

        calls = []

        async def failing(chat_id):
            calls.append(chat_id)
            self.k8s._start_failed_at[chat_id] = __import__("time").monotonic()
            raise RunnerUnavailableError()

        with patch("open_webui.utils.skill_k8s_sandbox._run_start", side_effect=failing):
            first = start_runner("chat-1")
            with self.assertRaises(RunnerUnavailableError):
                await first
            self.assertIs(start_runner("chat-1"), first)
            self.k8s._start_failed_at["chat-1"] -= 60
            second = start_runner("chat-1")
            self.assertIsNot(second, first)
            with self.assertRaises(RunnerUnavailableError):
                await second
        self.assertEqual(len(calls), 2)



class RunnerHealthTest(IsolatedAsyncioTestCase):
    async def _health(self, error=None):
        from open_webui.utils.skill_k8s_sandbox import _runner_health

        http = AsyncMock(side_effect=error) if error else AsyncMock(return_value={})
        with patch(
            "open_webui.utils.skill_k8s_sandbox._runner_base", AsyncMock(return_value="http://10.0.0.1:8888")
        ), patch("open_webui.utils.skill_k8s_sandbox._http_json", http):
            return await _runner_health(_runner("p", "u1"))

    async def test_answer_is_ok(self):
        self.assertEqual(await self._health(), "ok")

    async def test_error_status_is_unhealthy(self):
        error = RuntimeError("GET http://10.0.0.1:8888/health -> 503: b'{\"ok\": false}'")
        self.assertEqual(await self._health(error), "unhealthy")

    async def test_timeout_is_no_answer(self):
        error = RuntimeError("GET http://10.0.0.1:8888/health timed out after 2s")
        self.assertEqual(await self._health(error), "no_answer")

    async def test_connection_error_is_no_answer(self):
        error = RuntimeError("GET http://10.0.0.1:8888/health failed: Connection reset by peer")
        self.assertEqual(await self._health(error), "no_answer")


class RunnerStatusBrokenRunnerTest(IsolatedAsyncioTestCase):
    """The top-bar status: an explicit 503 deletes the claim; a broken bound runner reads paused."""

    def tearDown(self):
        _drop_runner("chat-1")

    def _claim(self, ready: bool) -> dict:
        return {
            "metadata": {"name": "runner-chat-1", "uid": "u1"},
            "status": {
                "sandbox": {"name": "pod-1"},
                "conditions": [{"type": "Ready", "status": "True" if ready else "False"}],
            },
        }

    def _pod(self, *, ready: bool, bound: bool) -> dict:
        annotations = {"weather-skills.io/bound": "chat-1"} if bound else {}
        return {
            "metadata": {"name": "pod-1", "annotations": annotations},
            "status": {
                "phase": "Running",
                "podIP": "10.0.0.1",
                "conditions": [{"type": "Ready", "status": "True" if ready else "False"}],
            },
        }

    async def test_cached_runner_answering_503_deletes_its_claim(self):
        _store_runner("chat-1", {"pod_ip": "10.0.0.1", "pod_name": "pod-1", "claim": {"metadata": {"uid": "u1"}}})
        with patch("open_webui.utils.skill_k8s_sandbox._runner_health", AsyncMock(return_value="unhealthy")), patch(
            "open_webui.utils.skill_k8s_sandbox.delete_claim", AsyncMock()
        ) as delete:
            status = await runner_status("chat-1")
        self.assertEqual(status["state"], "absent")
        delete.assert_awaited_once_with("chat-1", uid="u1")
        self.assertIsNone(_ready_cache.get("chat-1"))

    async def test_slow_cached_runner_on_a_ready_pod_stays_ready(self):
        _store_runner("chat-1", {"pod_ip": "10.0.0.1", "pod_name": "pod-1", "claim": {"metadata": {"uid": "u1"}}})
        with patch("open_webui.utils.skill_k8s_sandbox._runner_health", AsyncMock(return_value="no_answer")), patch(
            "open_webui.utils.skill_k8s_sandbox.get_pod", AsyncMock(return_value=self._pod(ready=True, bound=True))
        ), patch("open_webui.utils.skill_k8s_sandbox.delete_claim", AsyncMock()) as delete:
            status = await runner_status("chat-1")
        self.assertEqual(status["state"], "ready")
        delete.assert_not_awaited()

    async def test_ready_claim_whose_runner_answers_503_deletes_its_claim(self):
        with patch("open_webui.utils.skill_k8s_sandbox.get_claim", AsyncMock(return_value=self._claim(True))), patch(
            "open_webui.utils.skill_k8s_sandbox.get_pod", AsyncMock(return_value=self._pod(ready=True, bound=True))
        ), patch("open_webui.utils.skill_k8s_sandbox._runner_health", AsyncMock(return_value="unhealthy")), patch(
            "open_webui.utils.skill_k8s_sandbox.delete_claim", AsyncMock()
        ) as delete:
            status = await runner_status("chat-1")
        self.assertEqual(status["state"], "absent")
        delete.assert_awaited_once_with("chat-1", uid="u1")

    async def test_bound_runner_that_went_not_ready_reads_paused(self):
        with patch("open_webui.utils.skill_k8s_sandbox.get_claim", AsyncMock(return_value=self._claim(False))), patch(
            "open_webui.utils.skill_k8s_sandbox.get_pod", AsyncMock(return_value=self._pod(ready=False, bound=True))
        ):
            status = await runner_status("chat-1")
        self.assertEqual(status["state"], "absent")

    async def test_unbound_runner_that_is_not_ready_yet_reads_starting(self):
        with patch("open_webui.utils.skill_k8s_sandbox.get_claim", AsyncMock(return_value=self._claim(False))), patch(
            "open_webui.utils.skill_k8s_sandbox.get_pod", AsyncMock(return_value=self._pod(ready=False, bound=False))
        ):
            status = await runner_status("chat-1")
        self.assertEqual(status["state"], "starting")

    async def test_slow_answer_never_deletes(self):
        with patch("open_webui.utils.skill_k8s_sandbox.get_claim", AsyncMock(return_value=self._claim(True))), patch(
            "open_webui.utils.skill_k8s_sandbox.get_pod", AsyncMock(return_value=self._pod(ready=False, bound=True))
        ), patch("open_webui.utils.skill_k8s_sandbox._runner_health", AsyncMock(return_value="no_answer")), patch(
            "open_webui.utils.skill_k8s_sandbox.delete_claim", AsyncMock()
        ) as delete:
            status = await runner_status("chat-1")
        self.assertEqual(status["state"], "absent")
        delete.assert_not_awaited()
