from pathlib import Path
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import patch

from open_webui.utils.skill_k8s_sandbox import (
    PACKS_ANN,
    RUNNER_UV_CACHE_DIR,
    WAITING_STATUS,
    _drop_runner,
    _emit_waiting,
    _ready_cache,
    _installed_packs,
    _missing_packs,
    _pack_names,
    _runner_packs_root,
    _runner_workspace,
    _store_runner,
    _tar_pack,
    _uv_cache_dir,
    await_runner_for_chat,
    claim_name,
    delete_claim,
    emulator_enabled,
    in_cluster,
    remote_script_path,
    public_runner_state,
    runner_needs_wait,
    runner_metrics,
    runner_ready,
    runner_status,
    run_skill_on_runner,
    start_runner,
    use_direct_http,
)


class ClaimNameTest(TestCase):
    def test_strips_unsafe_characters(self):
        self.assertEqual(claim_name("abc_def"), "runner-abc-def")

    def test_truncates(self):
        name = claim_name("x" * 80)
        self.assertLessEqual(len(name), 63)
        self.assertTrue(name.startswith("runner-"))


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

    def test_installed_packs_are_top_level_dirs(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "weather-skills").mkdir()
            (root / ".hidden").mkdir()
            (root / "readme.txt").write_text("x")
            with patch.dict("os.environ", {"SKILLS_DIR": str(root)}, clear=False):
                packs = _installed_packs()
                self.assertEqual([p.name for p in packs], ["weather-skills"])
                self.assertEqual(_pack_names(packs), {"weather-skills"})
                self.assertEqual([p.name for p in _missing_packs({"weather-skills"})], [])
                self.assertEqual([p.name for p in _missing_packs(set())], ["weather-skills"])


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
        with patch("open_webui.utils.skill_k8s_sandbox.get_claim") as get_claim:
            status = await runner_status("chat-1")
        self.assertEqual(status["state"], "ready")
        get_claim.assert_not_called()

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
            "open_webui.utils.skill_k8s_sandbox._listed_packs",
            return_value={"weather-skills"},
        ), patch(
            "open_webui.utils.skill_k8s_sandbox._installed_packs",
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
            "open_webui.utils.skill_k8s_sandbox._listed_packs",
            return_value=set(),
        ), patch(
            "open_webui.utils.skill_k8s_sandbox._installed_packs",
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


class RecoverBrokenRunnerTest(IsolatedAsyncioTestCase):
    def tearDown(self):
        _drop_runner("chat-1")

    async def test_a_lost_exec_starts_a_new_runner(self):
        infos = [
            {"pod_ip": "10.0.0.1", "pod_name": "old"},
            {"pod_ip": "10.0.0.2", "pod_name": "new"},
        ]
        execs = []

        async def ensure(chat_id, *, emitter=None):
            info = infos.pop(0)
            _store_runner(chat_id, info)
            return info

        async def exec_on(chat_id, argv, **kwargs):
            execs.append(kwargs.get("info"))
            if len(execs) == 1:
                raise RuntimeError("POST http://10.0.0.1:8888/exec -> 502")
            return {"exit_code": 0, "stdout": "ok", "stderr": ""}

        with patch(
            "open_webui.utils.skill_k8s_sandbox.ensure_runner", side_effect=ensure
        ), patch(
            "open_webui.utils.skill_k8s_sandbox.exec_on_runner", side_effect=exec_on
        ), patch(
            "open_webui.utils.skill_k8s_sandbox.delete_claim"
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
        self.assertTrue(result["ok"])
        delete.assert_awaited()
        self.assertEqual(len(execs), 2)
        self.assertEqual(execs[1]["pod_ip"], "10.0.0.2")

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
