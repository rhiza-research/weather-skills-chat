import importlib.util
from io import StringIO
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

RUNTIME = Path(__file__).resolve().parents[1] / "sandbox_runtime.py"
SPEC = importlib.util.spec_from_file_location("sandbox_runtime", RUNTIME)
runtime = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime)


class SandboxRuntimeTest(TestCase):
    def test_exec_rejects_bad_cmd(self):
        self.assertEqual(runtime.run_exec({"cmd": "echo"})["exit_code"], 2)

    def test_exec_runs_echo(self):
        result = runtime.run_exec({"cmd": ["echo", "ok"], "cwd": ".", "timeout": 5})
        self.assertEqual(result["exit_code"], 0)
        self.assertIn("ok", result["stdout"])

    def test_exec_nices_the_child(self):
        import subprocess

        real = subprocess.Popen

        def spawn(*args, **kwargs):
            self.assertIs(kwargs.get("preexec_fn"), runtime._lower_child_priority)
            return real(*args, **kwargs)

        with patch.object(runtime.subprocess, "Popen", side_effect=spawn):
            result = runtime.run_exec({"cmd": ["echo", "ok"], "cwd": ".", "timeout": 5})
        self.assertEqual(result["exit_code"], 0)

    def test_metrics_are_a_snapshot(self):
        metrics = runtime.collect_metrics()
        self.assertIn("timestamp", metrics)
        self.assertIn("usage_usec", metrics["cpu"])
        self.assertGreaterEqual(metrics["memory_bytes"], 0)
        self.assertEqual(metrics["cpu_limit"], 3.0)
        self.assertGreater(metrics["memory_limit_bytes"], 0)

    def test_unpack_extracts_under_workspace(self):
        import base64
        import io
        import tarfile
        import tempfile

        previous = runtime.WORKSPACE
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            runtime.WORKSPACE = workspace
            try:
                buf = io.BytesIO()
                with tarfile.open(fileobj=buf, mode="w:gz") as tar:
                    info = tarfile.TarInfo(name="pack/hello.txt")
                    data = b"hi\n"
                    info.size = len(data)
                    tar.addfile(info, io.BytesIO(data))
                dest = workspace / ".skill-packs" / "pack"
                result = runtime.run_unpack(
                    {
                        "dest": str(dest),
                        "archive": base64.b64encode(buf.getvalue()).decode(),
                    }
                )
                self.assertTrue(result["ok"])
                self.assertEqual((dest / "hello.txt").read_text(), "hi\n")
            finally:
                runtime.WORKSPACE = previous

    def test_unpack_rejects_escape(self):
        result = runtime.run_unpack({"dest": "/tmp/nope", "archive": ""})
        self.assertFalse(result["ok"])

    def test_unpack_failure_goes_to_stderr(self):
        import tempfile

        previous = runtime.WORKSPACE
        err = StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            runtime.WORKSPACE = workspace
            try:
                with patch.object(runtime.sys, "stderr", err), patch.object(
                    runtime.subprocess,
                    "run",
                    side_effect=OSError("disk full"),
                ):
                    result = runtime.run_unpack(
                        {
                            "dest": str(workspace / "pack"),
                            "archive": "YQ==",
                        }
                    )
            finally:
                runtime.WORKSPACE = previous
        self.assertFalse(result["ok"])
        self.assertIn("unpack fail", err.getvalue())
        self.assertIn("disk full", err.getvalue())

    def test_exec_runtime_failure_goes_to_stderr(self):
        err = StringIO()
        with patch.object(runtime.sys, "stderr", err), patch.object(
            runtime.subprocess, "Popen", side_effect=OSError("no such file")
        ):
            result = runtime.run_exec({"cmd": ["uv", "run", "--script", "x.py"], "timeout": 5})
        self.assertEqual(result["exit_code"], 1)
        self.assertIn("exec fail", err.getvalue())

    def test_invalid_cmd_stays_off_stderr(self):
        err = StringIO()
        with patch.object(runtime.sys, "stderr", err):
            result = runtime.run_exec({"cmd": "echo"})
        self.assertEqual(result["exit_code"], 2)
        self.assertEqual(err.getvalue(), "")

    def test_unpack_allows_packs_beside_chat_workspace(self):
        import base64
        import io
        import tarfile
        import tempfile

        previous = runtime.WORKSPACE
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp)
            chat = empty / "chat"
            chat.mkdir()
            runtime.WORKSPACE = chat
            try:
                buf = io.BytesIO()
                with tarfile.open(fileobj=buf, mode="w:gz") as tar:
                    info = tarfile.TarInfo(name="pack/hello.txt")
                    data = b"hi\n"
                    info.size = len(data)
                    tar.addfile(info, io.BytesIO(data))
                dest = empty / ".skill-packs" / "pack"
                result = runtime.run_unpack(
                    {
                        "dest": str(dest),
                        "archive": base64.b64encode(buf.getvalue()).decode(),
                    }
                )
                self.assertTrue(result.get("ok"), result)
                self.assertEqual((dest / "hello.txt").read_text(), "hi\n")
            finally:
                runtime.WORKSPACE = previous

    def test_list_packs_names_dirs_beside_chat(self):
        import tempfile

        previous = runtime.WORKSPACE
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp)
            chat = empty / "chat"
            chat.mkdir()
            packs = empty / ".skill-packs"
            (packs / "plot").mkdir(parents=True)
            (packs / "fetch").mkdir()
            (packs / ".hidden").mkdir()
            runtime.WORKSPACE = chat
            try:
                self.assertEqual(runtime.list_packs()["packs"], ["fetch", "plot"])
            finally:
                runtime.WORKSPACE = previous

    def test_skill_label_from_script_path(self):
        self.assertEqual(
            runtime.skill_label(
                [
                    "uv",
                    "run",
                    "--script",
                    "/workspace/.skill-packs/pack/skills/plot/scripts/plot.py",
                    "--bbox",
                    "1/2/3/4",
                ]
            ),
            "plot",
        )
        self.assertEqual(
            runtime.skill_label(
                ["uv", "run", "--script", "/workspace/.skill-packs/probe-skill/scripts/probe_skill.py"]
            ),
            "probe_skill",
        )
        self.assertEqual(runtime.skill_label(["echo", "ok"]), "echo")
