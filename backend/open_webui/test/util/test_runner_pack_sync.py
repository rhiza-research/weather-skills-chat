"""A skill call makes sure the runner has its pack at the installed commit."""

from __future__ import annotations


import asyncio
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import open_webui.config  # noqa: F401  Runs the migrations: pack names read skill_pack.
from open_webui.models.skill_packs import SkillPacks
from open_webui.utils import skill_k8s_sandbox as sandbox

K = "open_webui.utils.skill_k8s_sandbox"


class _Packs(unittest.TestCase):
    """Pack checkouts on disk with skill_pack rows recording their commits."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.env = patch.dict("os.environ", {"SKILLS_DIR": str(self.tmp)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def _pack(self, name: str, commit=None, *, folder=None) -> Path:
        pack = folder or self.tmp / name
        scripts = pack / "skills" / "plot" / "scripts"
        scripts.mkdir(parents=True, exist_ok=True)
        (scripts / "plot.py").write_text("print(1)\n")
        if commit is not None:
            self._install(pack, commit)
        return pack

    def _install(self, pack: Path, commit: str):
        row = SkillPacks.insert(
            f"user-{uuid.uuid4()}",
            name=pack.name,
            git_url=f"https://github.com/example/{uuid.uuid4()}.git",
            git_ref="main",
            commit_sha=commit,
            local_path=str(pack),
            organization_id=f"org-{uuid.uuid4()}",
        )
        self.addCleanup(SkillPacks.delete, row.id)
        return row


class PackVersionTest(_Packs):
    def test_a_pack_is_named_by_its_installed_commit(self):
        pack = self._pack("weather-skills__main", "a" * 40)
        self.assertEqual(sandbox._runner_pack_name(pack), "weather-skills__main--aaaaaaaaaaaa")

    def test_an_update_changes_the_name(self):
        pack = self._pack("p")
        row = self._install(pack, "a" * 40)
        before = sandbox._runner_pack_name(pack)
        SkillPacks.update(row.id, {"commit_sha": "d" * 40})
        self.assertEqual(sandbox._runner_pack_name(pack), "p--dddddddddddd")
        self.assertNotEqual(before, "p--dddddddddddd")

    def test_the_latest_install_of_a_shared_folder_wins(self):
        # One person installing the same repo and ref in two organizations
        # gets two rows for one folder; the folder holds the last checkout.
        pack = self._pack("p")
        self._install(pack, "a" * 40)
        time.sleep(1.1)
        self._install(pack, "b" * 40)
        self.assertEqual(sandbox._runner_pack_name(pack), "p--bbbbbbbbbbbb")

    def test_a_pack_with_no_recorded_commit_keeps_its_folder_name(self):
        self.assertEqual(sandbox._runner_pack_name(self._pack("plain")), "plain")

    def test_the_script_path_uses_the_versioned_folder(self):
        pack = self._pack("p", "a" * 40)
        path = sandbox.remote_script_path(
            pack / "skills" / "plot", pack / "skills" / "plot" / "scripts" / "plot.py"
        )
        self.assertEqual(
            path, "/workspace/.skill-packs/p--aaaaaaaaaaaa/skills/plot/scripts/plot.py"
        )


class StartAndUnpackTest(_Packs):
    def test_missing_packs_compare_versioned_names(self):
        pack = self._pack("p", "a" * 40)
        self.assertEqual(sandbox._pack_names([pack]), {"p--aaaaaaaaaaaa"})
        # An old unversioned copy on the runner does not count.
        self.assertEqual(sandbox._missing_packs({"p"}, [pack]), [pack])
        self.assertEqual(sandbox._missing_packs({"p--aaaaaaaaaaaa"}, [pack]), [])

    def test_the_archive_unpacks_into_the_versioned_folder(self):
        # The runner extracts the archive into its packs folder, so the
        # folder name inside the archive is the one that ends up there.
        import base64
        import io
        import json
        import tarfile

        pack = self._pack("p", "a" * 40)
        dest, body = sandbox._unpack_request(pack / "skills" / "plot")
        self.assertEqual(dest, "/workspace/.skill-packs/p--aaaaaaaaaaaa")
        archive = base64.b64decode(json.loads(body)["archive"])
        names = tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz").getnames()
        self.assertIn("p--aaaaaaaaaaaa/skills/plot/scripts/plot.py", names)
        self.assertFalse(any(n.startswith("p/") for n in names))


class CallPackSyncTest(_Packs, unittest.IsolatedAsyncioTestCase):
    """run_skill_on_runner copies a pack the runner lacks before running."""

    def setUp(self):
        super().setUp()
        self.pack = self._pack("p")
        self.row = self._install(self.pack, "a" * 40)
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
        SkillPacks.update(self.row.id, {"commit_sha": "e" * 40})
        await self._call()
        pushes = [e for e in self.events if e.startswith("push")]
        self.assertEqual(pushes, ["push p--aaaaaaaaaaaa", "push p--eeeeeeeeeeee"])

    async def test_parallel_calls_copy_a_pack_once(self):
        await asyncio.gather(self._call(), self._call(), self._call())
        self.assertEqual(sum(e.startswith("push") for e in self.events), 1)
        self.assertEqual(sum(e.startswith("exec") for e in self.events), 3)


if __name__ == "__main__":
    unittest.main()
