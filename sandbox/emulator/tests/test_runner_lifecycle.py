"""Runner lifecycle through the chat backend + emulator.

A runner that dies mid-skill: the skill gets RUNNER_DIED_MESSAGE and the chat
reads paused. Nothing is deleted or claimed until the next tool call, whose
/health check replaces the dead runner with exactly one new one.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import shutil
import socket
import tempfile
import threading
import time
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("sandbox_emulator", HERE / "emulator.py")
emulator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(emulator)

from open_webui.utils import skill_k8s_sandbox as k8s
from open_webui.utils.skill_k8s_sandbox import public_runner_state

DIED_MESSAGE = k8s.RUNNER_DIED_MESSAGE

SLEEP_SCRIPT = """\
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
import os
import sys
import time
from pathlib import Path
# Tells the test this skill is running on the runner before it kills it.
Path(f"sleep-started-{os.getpid()}").touch()
time.sleep(float(sys.argv[1]) if len(sys.argv) > 1 else 60)
print("slept")
"""

HELLO_SCRIPT = """\
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
print("hello")
"""


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _write_skill(root: Path, name: str, script: str, filename: str) -> Path:
    skill = root / name
    scripts = skill / "scripts"
    scripts.mkdir(parents=True)
    (scripts / filename).write_text(script, encoding="utf-8")
    return skill


class RunnerLifecycleTest(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.artifacts = self.tmp / "artifacts"
        self.skills = self.tmp / "skills"
        self.artifacts.mkdir()
        self.skills.mkdir()
        self.sleep_skill = _write_skill(self.skills, "die-wait", SLEEP_SCRIPT, "sleep.py")
        self.hello_skill = _write_skill(self.skills, "die-hello", HELLO_SCRIPT, "hello.py")

        self.api_port = _free_port()
        self.bind_port = _free_port()
        self.runner_port = _free_port()
        self.env = {
            "SKILL_K8S_EMULATOR": "1",
            "SKILL_K8S_APISERVER": f"http://127.0.0.1:{self.api_port}",
            "SKILL_K8S_BIND_TOKEN": "dev",
            "SKILL_K8S_BIND_PORT": str(self.bind_port),
            "SKILL_K8S_SANDBOX_NAMESPACE": "weather-skills-sandbox-staging",
            "SKILL_SANDBOX_BACKEND": "k8s",
            "SKILL_K8S_SANDBOX_ENABLED": "true",
            "ARTIFACTS_DIR": str(self.artifacts),
            "SKILLS_DIR": str(self.skills),
            "SKILL_K8S_EMULATOR_API_PORT": str(self.api_port),
            "SKILL_K8S_EMULATOR_RUNNER_PORT": str(self.runner_port),
            "SKILL_K8S_EMULATOR_START_DELAY": "0",
            "SKILL_K8S_UV_CACHE_DIR": str(self.tmp / "uv-cache"),
        }
        self._prev_env = {key: os.environ.get(key) for key in self.env}
        os.environ.update(self.env)

        emulator.TOKEN = "dev"
        emulator.API_PORT = self.api_port
        emulator.BIND_PORT = self.bind_port
        emulator.NS = "weather-skills-sandbox-staging"
        emulator._claims.clear()
        emulator._pods.clear()
        emulator._procs.clear()
        emulator._exit_codes.clear()
        emulator._next_port = self.runner_port

        self.runtime_starts = 0
        orig_start = emulator._start_runtime

        def counted_start(chat_id: str, port: int) -> None:
            self.runtime_starts += 1
            orig_start(chat_id, port)

        self._orig_start = orig_start
        emulator._start_runtime = counted_start

        self.api = emulator.ThreadingHTTPServer(
            ("127.0.0.1", self.api_port), emulator.ApiHandler
        )
        self.bind = emulator.ThreadingHTTPServer(
            ("127.0.0.1", self.bind_port), emulator.BindHandler
        )
        threading.Thread(target=self.api.serve_forever, daemon=True).start()
        threading.Thread(target=self.bind.serve_forever, daemon=True).start()

        k8s._ready_cache.clear()
        k8s._starts.clear()
        k8s._start_failed_at.clear()
        self._packs_patch = patch(
            "open_webui.utils.skill_k8s_sandbox._packs_for_chat",
            return_value=[],
        )
        self._packs_patch.start()

    async def asyncTearDown(self):
        emulator._start_runtime = self._orig_start
        self.api.shutdown()
        self.bind.shutdown()
        for chat_id in list(emulator._procs):
            emulator._stop_runtime(chat_id)
        k8s._ready_cache.clear()
        k8s._starts.clear()
        if getattr(self, "_packs_patch", None) is not None:
            self._packs_patch.stop()
        for key, value in self._prev_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _stage_pack(self, chat_id: str, skill: Path) -> None:
        dest = self.artifacts / chat_id / ".skill-packs" / skill.name / "scripts"
        dest.mkdir(parents=True, exist_ok=True)
        for script in (skill / "scripts").iterdir():
            shutil.copy2(script, dest / script.name)

    def _kill_runtime(self, chat_id: str) -> None:
        """Kill the exec process. Leave the claim, as a crashed pod would."""
        emulator._stop_runtime(chat_id)

    def _live_runtimes(self) -> int:
        return sum(1 for proc in emulator._procs.values() if proc.poll() is None)

    def _claim_count(self) -> int:
        return len(emulator._claims)

    async def _public_state(self, chat_id: str) -> str:
        status = await k8s.runner_status(chat_id)
        return public_runner_state(status.get("state"))

    async def _await_dead_skills(self, *tasks: asyncio.Task, timeout: float = 5):
        done, pending = await asyncio.wait(tasks, timeout=timeout)
        if pending:
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            self.fail(
                "skill kept running after the runner died "
                "(likely a silent replacement on a new runner) "
                f"starts={self.runtime_starts} claims={self._claim_count()} "
                f"live={self._live_runtimes()}"
            )
        results = [task.result() for task in tasks]
        return results[0] if len(results) == 1 else results

    async def _wait_until_in_flight(
        self, chat_id: str, *tasks: asyncio.Task, timeout: float = 30
    ) -> None:
        """Wait until every sleep skill has started on the runner (its marker file)."""
        workspace = self.artifacts / chat_id
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if any(task.done() for task in tasks):
                results = []
                for task in tasks:
                    if task.done():
                        results.append(task.result() if not task.cancelled() else "cancelled")
                self.fail(f"skill returned before the runner was killed: {results}")
            if len(list(workspace.glob("sleep-started-*"))) >= len(tasks):
                return
            await asyncio.sleep(0.1)
        self.fail("timed out waiting for sleep skill to start on the runner")

    async def _run(self, chat_id: str, skill: Path, script: str, argv: list | None = None):
        self._stage_pack(chat_id, skill)
        return await k8s.run_skill_on_runner(
            chat_id=chat_id,
            skill_dir=skill,
            script_path=skill / "scripts" / script,
            args=list(argv or []),
            env={},
            timeout=30,
        )

    async def test_idle_death_goes_degraded_then_paused_then_next_skill_claims_one_runner(self):
        chat_id = "idle-death"
        await k8s.ensure_runner(chat_id)
        self.assertEqual(await self._public_state(chat_id), "ready")
        self.assertEqual(self.runtime_starts, 1)
        first_uid = next(iter(emulator._pods.values()))["metadata"]["uid"]

        self._kill_runtime(chat_id)
        self.assertEqual(
            await self._public_state(chat_id),
            "degraded",
            "an idle dead runner whose claim is still there must read degraded, not ready",
        )
        self.assertEqual(self._live_runtimes(), 0)

        # The cluster controller releases a bound runner that stays not ready.
        await k8s.delete_claim(chat_id)
        self.assertEqual(await self._public_state(chat_id), "paused")

        result = await self._run(chat_id, self.hello_skill, "hello.py")
        self.assertTrue(result.get("ok"), result)
        self.assertEqual(await self._public_state(chat_id), "ready")
        self.assertEqual(self._claim_count(), 1)
        self.assertEqual(self._live_runtimes(), 1)
        self.assertEqual(self.runtime_starts, 2)
        new_uid = next(iter(emulator._pods.values()))["metadata"]["uid"]
        self.assertNotEqual(new_uid, first_uid)

    async def test_one_in_flight_death_reads_degraded_and_tells_the_user_to_retry(self):
        chat_id = "one-in-flight"
        await k8s.ensure_runner(chat_id)
        starts_before_fail = self.runtime_starts

        task = asyncio.create_task(
            self._run(chat_id, self.sleep_skill, "sleep.py", argv=["20"])
        )
        await self._wait_until_in_flight(chat_id, task)
        self._kill_runtime(chat_id)
        result = await self._await_dead_skills(task)

        self.assertFalse(result.get("ok"), result)
        self.assertEqual(result.get("stderr"), DIED_MESSAGE)
        self.assertEqual(await self._public_state(chat_id), "degraded")
        self.assertEqual(
            self.runtime_starts,
            starts_before_fail,
            "dying mid-skill must not claim a replacement until the next tool call",
        )
        self.assertEqual(self._claim_count(), 1, "a failed tool call must not delete the claim")
        self.assertEqual(self._live_runtimes(), 0)

        retry = await self._run(chat_id, self.hello_skill, "hello.py")
        self.assertTrue(retry.get("ok"), retry)
        self.assertEqual(self._claim_count(), 1)
        self.assertEqual(self._live_runtimes(), 1)
        self.assertEqual(self.runtime_starts, starts_before_fail + 1)

    async def test_many_in_flight_deaths_do_not_claim_extra_runners(self):
        chat_id = "many-in-flight"
        await k8s.ensure_runner(chat_id)
        starts_before_fail = self.runtime_starts

        tasks = [
            asyncio.create_task(
                self._run(chat_id, self.sleep_skill, "sleep.py", argv=["20"])
            )
            for _ in range(3)
        ]
        await self._wait_until_in_flight(chat_id, *tasks)
        self._kill_runtime(chat_id)
        results = await self._await_dead_skills(*tasks)

        for result in results:
            self.assertFalse(result.get("ok"), result)
            self.assertEqual(result.get("stderr"), DIED_MESSAGE)
        self.assertEqual(await self._public_state(chat_id), "degraded")
        self.assertEqual(
            self.runtime_starts,
            starts_before_fail,
            "parallel in-flight failures claimed extra runners "
            f"(starts={self.runtime_starts}, claims={self._claim_count()}, "
            f"live={self._live_runtimes()})",
        )
        self.assertEqual(self._claim_count(), 1, "a failed tool call must not delete the claim")
        self.assertEqual(self._live_runtimes(), 0)

        retry = await self._run(chat_id, self.hello_skill, "hello.py")
        self.assertTrue(retry.get("ok"), retry)
        self.assertEqual(self._claim_count(), 1)
        self.assertEqual(self._live_runtimes(), 1)
        self.assertEqual(self.runtime_starts, starts_before_fail + 1)
