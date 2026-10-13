import importlib.util
from pathlib import Path
from unittest import TestCase

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

    def test_metrics_are_a_snapshot(self):
        metrics = runtime.collect_metrics()
        self.assertIn("timestamp", metrics)
