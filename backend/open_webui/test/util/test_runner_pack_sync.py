"""A skill call makes sure the runner has its pack at the current version."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from open_webui.utils import skill_k8s_sandbox as sandbox

K = "open_webui.utils.skill_k8s_sandbox"


def _git_pack(root: Path, name: str, commit: str, packed: bool = False) -> Path:
    """A pack checkout whose .git HEAD points at commit."""
    pack = root / name
    (pack / "skills" / "plot" / "scripts").mkdir(parents=True)
    (pack / "skills" / "plot" / "scripts" / "plot.py").write_text("print(1)\n")
    git = pack / ".git"
    git.mkdir()
    (git / "HEAD").write_text("ref: refs/heads/main\n")
    if packed:
        (git / "packed-refs").write_text(f"# pack-refs\n{commit} refs/heads/main\n")
    else:
        (git / "refs" / "heads").mkdir(parents=True)
        (git / "refs" / "heads" / "main").write_text(commit + "\n")
    return pack


class PackVersionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_a_git_pack_is_named_by_its_commit(self):
        pack = _git_pack(self.tmp, "weather-skills__main", "a" * 40)
        self.assertEqual(sandbox._runner_pack_name(pack), "weather-skills__main--aaaaaaaaaaaa")

    def test_packed_refs_and_detached_heads(self):
        pack = _git_pack(self.tmp, "p", "b" * 40, packed=True)
        self.assertEqual(sandbox._runner_pack_name(pack), "p--bbbbbbbbbbbb")
        (pack / ".git" / "HEAD").write_text("c" * 40 + "\n")
        self.assertEqual(sandbox._runner_pack_name(pack), "p--cccccccccccc")

    def test_an_update_changes_the_name(self):
        pack = _git_pack(self.tmp, "p", "a" * 40)
        before = sandbox._runner_pack_name(pack)
        (pack / ".git" / "refs" / "heads" / "main").write_text("d" * 40 + "\n")
        self.assertNotEqual(sandbox._runner_pack_name(pack), before)

    def test_a_pack_without_git_keeps_its_folder_name(self):
        (self.tmp / "plain").mkdir()
        self.assertEqual(sandbox._runner_pack_name(self.tmp / "plain"), "plain")

    def test_the_script_path_uses_the_versioned_folder(self):
        pack = _git_pack(self.tmp, "p", "a" * 40)
        with patch.dict("os.environ", {"SKILLS_DIR": str(self.tmp)}):
            path = sandbox.remote_script_path(
                pack / "skills" / "plot", pack / "skills" / "plot" / "scripts" / "plot.py"
            )
        self.assertEqual(
            path, "/workspace/.skill-packs/p--aaaaaaaaaaaa/skills/plot/scripts/plot.py"
        )


class CallPackSyncTest(unittest.IsolatedAsyncioTestCase):
    """run_skill_on_runner copies a pack the runner lacks before running."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.pack = _git_pack(self.tmp, "p", "a" * 40)
        self.info = {"pod_ip": "10.0.0.1", "pod_name": "runner-1"}
        self.events: list[str] = []
        self.listed: set[str] = set()

        async def listed(info):
            self.events.append("list")
            return set(self.listed)

        async def push(info, skill_dir):
            name = sandbox._runner_pack_name(sandbox._pack_root(skill_dir))
            self.events.append(f"push {name}")
            await asyncio.sleep(0)
            return f"/workspace/.skill-packs/{name}"

        async def exec_on(chat_id, argv, **kw):
            self.events.append(f"exec {argv[3]}")
            return {"exit_code": 0, "stdout": "ok", "stderr": ""}

        patches = [
            patch.dict("os.environ", {"SKILLS_DIR": str(self.tmp)}),
            patch(f"{K}.ensure_runner", AsyncMock(return_value=self.info)),
            patch(f"{K}.hold_runner_for_skill", AsyncMock()),
            patch(f"{K}._listed_packs", side_effect=listed),
            patch(f"{K}._ensure_pack_on_runner", side_effect=push),
            patch(f"{K}.exec_on_runner", side_effect=exec_on),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    async def _call(self):
        skill_dir = self.pack / "skills" / "plot"
        return await sandbox.run_skill_on_runner(
            chat_id="chat-1",
            skill_dir=skill_dir,
            script_path=skill_dir / "scripts" / "plot.py",
            args=[],
            env={},
            timeout=60,
        )

    async def test_a_missing_pack_is_copied_before_the_call_runs(self):
        await self._call()
        self.assertEqual(
            self.events,
            [
                "list",
                "push p--aaaaaaaaaaaa",
                "exec /workspace/.skill-packs/p--aaaaaaaaaaaa/skills/plot/scripts/plot.py",
            ],
        )

    async def test_a_pack_already_there_is_not_copied_or_listed_again(self):
        self.listed = {"p--aaaaaaaaaaaa"}
        await self._call()
        await self._call()
        self.assertEqual(self.events.count("list"), 1)
        self.assertFalse(any(e.startswith("push") for e in self.events))

    async def test_an_updated_pack_is_copied_again(self):
        await self._call()
        (self.pack / ".git" / "refs" / "heads" / "main").write_text("e" * 40 + "\n")
        await self._call()
        pushes = [e for e in self.events if e.startswith("push")]
        self.assertEqual(pushes, ["push p--aaaaaaaaaaaa", "push p--eeeeeeeeeeee"])

    async def test_parallel_calls_copy_a_pack_once(self):
        await asyncio.gather(self._call(), self._call(), self._call())
        self.assertEqual(sum(e.startswith("push") for e in self.events), 1)
        self.assertEqual(sum(e.startswith("exec") for e in self.events), 3)


class StartUsesVersionedNamesTest(unittest.TestCase):
    def test_missing_packs_compare_versioned_names(self):
        tmp = Path(tempfile.mkdtemp())
        pack = _git_pack(tmp, "p", "a" * 40)
        self.assertEqual(sandbox._pack_names([pack]), {"p--aaaaaaaaaaaa"})
        # An old unversioned copy on the runner does not count.
        self.assertEqual(sandbox._missing_packs({"p"}, [pack]), [pack])
        self.assertEqual(sandbox._missing_packs({"p--aaaaaaaaaaaa"}, [pack]), [])


if __name__ == "__main__":
    unittest.main()


class UnpackNameTest(unittest.TestCase):
    def test_the_archive_unpacks_into_the_versioned_folder(self):
        # The runner extracts the archive into the packs folder, so the
        # folder name inside the archive is the one that ends up there.
        import base64
        import io
        import json
        import tarfile

        tmp = Path(tempfile.mkdtemp())
        pack = _git_pack(tmp, "p", "a" * 40)
        with patch.dict("os.environ", {"SKILLS_DIR": str(tmp)}):
            dest, body = sandbox._unpack_request(pack / "skills" / "plot")
        self.assertEqual(dest, "/workspace/.skill-packs/p--aaaaaaaaaaaa")
        archive = base64.b64decode(json.loads(body)["archive"])
        names = tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz").getnames()
        self.assertIn("p--aaaaaaaaaaaa/skills/plot/scripts/plot.py", names)
        self.assertFalse(any(n.startswith("p/") for n in names))
