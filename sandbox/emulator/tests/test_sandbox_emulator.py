import importlib.util
import os
import socket
import threading
from pathlib import Path
from unittest import IsolatedAsyncioTestCase, TestCase

HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("sandbox_emulator", HERE / "emulator.py")
emulator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(emulator)
LOCAL = importlib.util.spec_from_file_location("local_runtime", HERE / "local_runtime.py")
local_runtime = importlib.util.module_from_spec(LOCAL)
LOCAL.loader.exec_module(local_runtime)


class StartDelayTest(TestCase):
    def test_default_is_immediate(self):
        os.environ.pop("SKILL_K8S_EMULATOR_START_DELAY", None)
        self.assertEqual(emulator._start_delay(), 0.0)

    def test_reads_seconds(self):
        os.environ["SKILL_K8S_EMULATOR_START_DELAY"] = "15"
        self.assertEqual(emulator._start_delay(), 15.0)
        os.environ.pop("SKILL_K8S_EMULATOR_START_DELAY", None)

    def test_unready_claim_has_false_condition(self):
        claim = emulator._make_claim("c1", "runner-c1", "pod-1", ready=False)
        self.assertFalse(claim["status"]["ready"])
        self.assertEqual(claim["status"]["conditions"][0]["status"], "False")


class LocalRuntimeMetricsTest(TestCase):
    def test_process_metrics(self):
        metrics = local_runtime.collect_metrics()
        self.assertGreater(metrics["memory_bytes"], 0)
        self.assertGreaterEqual(metrics["cpu"]["usage_usec"], 0)

    def test_maps_workspace_paths_to_emulator_dir(self):
        root = "/data/artifacts/chat-1"
        body = local_runtime.remap_exec_body(
            {
                "cmd": ["uv", "run", "--script", "/workspace/chat/.skill-packs/x/scripts/x.py"],
                "cwd": "/workspace/chat",
                "env": {
                    "HOME": "/workspace/chat",
                    "WEATHER_INTERMEDIATE_DIR": "/workspace/chat/intermediate_results",
                    "UV_CACHE_DIR": "/workspace/.uv-cache",
                    "OTHER": "keep",
                },
            },
            workspace=root,
        )
        self.assertEqual(body["cwd"], root)
        self.assertEqual(body["cmd"][-1], f"{root}/.skill-packs/x/scripts/x.py")
        self.assertEqual(body["env"]["HOME"], root)
        self.assertEqual(body["env"]["WEATHER_INTERMEDIATE_DIR"], f"{root}/intermediate_results")
        self.assertEqual(body["env"]["UV_CACHE_DIR"], "/data/artifacts/.uv-cache")
        self.assertEqual(body["env"]["OTHER"], "keep")


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


class SandboxEmulatorTest(IsolatedAsyncioTestCase):
    async def test_claim_bind_and_exec(self):
        from open_webui.utils import skill_k8s_sandbox as k8s

        import tempfile

        tmp = tempfile.mkdtemp()
        artifacts = Path(tmp) / "artifacts"
        artifacts.mkdir()
        api_port = _free_port()
        bind_port = _free_port()
        runner_port = _free_port()
        env = {
            "SKILL_K8S_EMULATOR": "1",
            "SKILL_K8S_APISERVER": f"http://127.0.0.1:{api_port}",
            "SKILL_K8S_BIND_TOKEN": "dev",
            "SKILL_K8S_BIND_PORT": str(bind_port),
            "SKILL_K8S_SANDBOX_NAMESPACE": "weather-skills-sandbox-staging",
            "ARTIFACTS_DIR": str(artifacts),
            "SKILL_K8S_EMULATOR_API_PORT": str(api_port),
            "SKILL_K8S_EMULATOR_RUNNER_PORT": str(runner_port),
            "SKILL_K8S_EMULATOR_START_DELAY": "0",
        }
        for key, value in env.items():
            os.environ[key] = value
        emulator.TOKEN = "dev"
        emulator.API_PORT = api_port
        emulator.BIND_PORT = bind_port
        emulator.NS = "weather-skills-sandbox-staging"
        emulator._claims.clear()
        emulator._pods.clear()
        emulator._procs.clear()
        emulator._next_port = runner_port

        api = emulator.ThreadingHTTPServer(("127.0.0.1", api_port), emulator.ApiHandler)
        bind = emulator.ThreadingHTTPServer(
            ("127.0.0.1", bind_port), emulator.BindHandler
        )
        threading.Thread(target=api.serve_forever, daemon=True).start()
        threading.Thread(target=bind.serve_forever, daemon=True).start()
        try:
            info = await k8s.ensure_runner("emu-chat")
            self.assertEqual(info["pod_ip"], emulator._host())
            result = await k8s.exec_on_runner(
                "emu-chat",
                ["python3", "-c", "print('emu-ok')"],
                cwd=str(artifacts / "emu-chat"),
            )
            self.assertEqual(result.get("exit_code"), 0)
            self.assertIn("emu-ok", result.get("stdout") or "")
            metrics = await k8s.runner_metrics("emu-chat")
            self.assertGreater(metrics.get("memory_bytes") or 0, 0)
            self.assertGreaterEqual((metrics.get("cpu") or {}).get("usage_usec") or 0, 0)
            await k8s.delete_claim("emu-chat")
        finally:
            api.shutdown()
            bind.shutdown()
            for chat_id in list(emulator._procs):
                emulator._stop_runtime(chat_id)
            for key in env:
                os.environ.pop(key, None)
