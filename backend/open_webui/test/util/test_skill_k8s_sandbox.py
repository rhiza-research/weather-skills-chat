from pathlib import Path
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import patch

from open_webui.utils.skill_k8s_sandbox import (
    WAITING_STATUS,
    _emit_waiting,
    _runner_packs_root,
    _runner_workspace,
    _tar_pack,
    _uv_cache_dir,
    await_runner_for_chat,
    claim_name,
    delete_claim,
    emulator_enabled,
    in_cluster,
    remote_script_path,
    runner_needs_wait,
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
            self.assertEqual(_uv_cache_dir("/workspace/chat"), "/workspace/.uv-cache")


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
            {"description": WAITING_STATUS, "done": False},
        )

    async def test_hides_when_runner_is_ready(self):
        events = []

        async def emitter(event):
            events.append(event)

        await _emit_waiting(emitter, True)
        self.assertTrue(events[0]["data"]["hidden"])
        self.assertTrue(events[0]["data"]["done"])


class AwaitRunnerForChatTest(IsolatedAsyncioTestCase):
    async def test_skips_when_runner_path_is_off(self):
        with patch.dict(
            "os.environ",
            {"SKILL_SANDBOX_BACKEND": "landlock", "SKILL_K8S_SANDBOX_ENABLED": "false"},
            clear=False,
        ), patch("open_webui.utils.skill_k8s_sandbox.ensure_runner") as ensure:
            await await_runner_for_chat("chat-1")
            ensure.assert_not_called()

    async def test_skips_temporary_chat(self):
        with patch.dict(
            "os.environ",
            {"SKILL_SANDBOX_BACKEND": "k8s", "SKILL_K8S_SANDBOX_ENABLED": "true"},
            clear=False,
        ), patch("open_webui.utils.skill_k8s_sandbox.ensure_runner") as ensure:
            await await_runner_for_chat("local")
            await await_runner_for_chat(None)
            ensure.assert_not_called()

    async def test_waits_for_saved_chat(self):
        with patch.dict(
            "os.environ",
            {"SKILL_SANDBOX_BACKEND": "k8s", "SKILL_K8S_SANDBOX_ENABLED": "true"},
            clear=False,
        ), patch(
            "open_webui.utils.skill_k8s_sandbox.ensure_runner", return_value={}
        ) as ensure:
            await await_runner_for_chat("chat-1", emitter="e")
            ensure.assert_awaited_once_with("chat-1", emitter="e")


class DeleteClaimTest(IsolatedAsyncioTestCase):
    async def test_missing_claim_is_ok(self):
        with patch(
            "open_webui.utils.skill_k8s_sandbox._k8s",
            side_effect=RuntimeError("k8s DELETE ... -> 404: b''"),
        ):
            await delete_claim("missing")
