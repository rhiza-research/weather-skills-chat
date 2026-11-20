"""Artifact listing: path, depth and provenance options, run off the event loop."""

from __future__ import annotations

import asyncio
import html
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from open_webui.routers import artifacts as artifacts_router
from open_webui.utils import artifacts as artifacts_utils
from open_webui.utils.artifacts import list_artifacts, list_artifacts_async
from open_webui.utils.auth import get_verified_user
from open_webui.utils.builtin_tools import list_artifacts as list_artifacts_tool

CHAIN = [
    {"skill": "dynamical-fetch", "version": "0.0.4", "args": {}, "input": None},
    {"skill": "plot", "version": "1.0.0", "args": {}, "input": "precip.zarr"},
]


def _page_with_provenance() -> str:
    content = html.escape(json.dumps(CHAIN), quote=True)
    return (
        "<!doctype html><html><head>"
        f'<meta name="weather_skills_history" content="{content}">'
        "</head><body></body></html>"
    )


class SandboxCase(unittest.TestCase):
    """runs/2024/day1/out.csv, plots/map.html and summary.html (both with
    provenance), notes.csv"""

    chat_id = "chat-opts"
    # chat_sandbox always creates intermediate_results.
    top = {"intermediate_results", "notes.csv", "plots", "runs", "summary.html"}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.artifacts = Path(self.tmp.name) / "artifacts"
        root = self.artifacts / self.chat_id
        (root / "runs" / "2024" / "day1").mkdir(parents=True)
        (root / "runs" / "2024" / "day1" / "out.csv").write_text("a\n")
        (root / "plots").mkdir()
        (root / "plots" / "map.html").write_text(_page_with_provenance())
        (root / "summary.html").write_text(_page_with_provenance())
        (root / "notes.csv").write_text("a,b\n")
        self.patch = patch("open_webui.utils.artifacts.ARTIFACTS_DIR", self.artifacts)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def paths(self, **kwargs) -> dict:
        return {i["path"]: i for i in list_artifacts(self.chat_id, **kwargs)}


class ListArtifactsOptionsTest(SandboxCase):
    def test_default_lists_every_level(self):
        items = self.paths()
        self.assertIn("runs/2024/day1/out.csv", items)
        self.assertFalse(any(i.get("truncated") for i in items.values()))

    def test_provenance_depth_none_reads_every_level(self):
        items = self.paths(provenance_depth=None)
        self.assertEqual(items["plots/map.html"]["provenance"], ["dynamical-fetch", "plot"])

    def test_depth_one_lists_top_level_and_marks_folders(self):
        items = self.paths(depth=1)
        self.assertEqual(set(items), self.top)
        self.assertTrue(items["runs"]["truncated"])
        self.assertTrue(items["plots"]["truncated"])
        self.assertNotIn("truncated", items["notes.csv"])

    def test_depth_two(self):
        items = self.paths(depth=2)
        self.assertIn("runs/2024", items)
        self.assertTrue(items["runs/2024"]["truncated"])
        self.assertNotIn("runs/2024/day1", items)
        self.assertNotIn("truncated", items["runs"])

    def test_path_lists_the_entry_and_what_is_under_it(self):
        items = self.paths(path="runs", depth=1)
        self.assertEqual(set(items), {"runs", "runs/2024"})
        self.assertNotIn("truncated", items["runs"])
        self.assertTrue(items["runs/2024"]["truncated"])

    def test_path_matches_filtering_the_full_listing(self):
        root = self.artifacts / self.chat_id
        (root / "store.zarr" / "precip").mkdir(parents=True)
        (root / "store.zarr" / ".zgroup").write_text("{}")
        (root / "store.zarr" / "precip" / "0").write_text("x")
        (root / ".cache" / "deep").mkdir(parents=True)
        (root / ".cache" / "deep" / "x").write_text("x")
        # Provenance depth counts from path, so read it everywhere in both.
        full = list_artifacts(self.chat_id, provenance_depth=None)
        for prefix in [
            "runs", "runs/", "runs/2024", "plots", "notes.csv", "nope",
            "store.zarr", "store.zarr/precip", ".cache", ".cache/deep",
        ]:
            base = prefix.rstrip("/") + "/"
            expected = [
                e for e in full
                if e["path"] == prefix or e["path"].startswith(base)
            ]
            self.assertEqual(
                list_artifacts(self.chat_id, path=prefix, provenance_depth=None), expected, prefix
            )

    def test_path_skips_folders_that_do_not_lead_to_it(self):
        walked = []
        real = Path.iterdir

        def spy(directory):
            walked.append(directory.name)
            return real(directory)

        with patch.object(Path, "iterdir", spy):
            list_artifacts(self.chat_id, path="runs/2024")
        self.assertNotIn("plots", walked)
        self.assertNotIn("intermediate_results", walked)

    def test_provenance_off_skips_file_reads(self):
        with patch.object(artifacts_utils, "provenance_for_html") as read:
            items = self.paths(provenance=False)
        read.assert_not_called()
        self.assertEqual(items["plots/map.html"]["kind"], "html")
        self.assertNotIn("provenance", items["plots/map.html"])

    def test_provenance_is_read_for_the_top_level_by_default(self):
        with patch.object(
            artifacts_utils, "provenance_for_html", wraps=artifacts_utils.provenance_for_html
        ) as read:
            items = self.paths()
        self.assertEqual(items["summary.html"]["provenance"], ["dynamical-fetch", "plot"])
        self.assertNotIn("provenance", items["plots/map.html"])
        self.assertIn("plots/map.html", items)
        self.assertEqual(read.call_count, 1)

    def test_provenance_depth_counts_from_path(self):
        items = self.paths(path="plots")
        self.assertEqual(items["plots/map.html"]["provenance"], ["dynamical-fetch", "plot"])

    def test_provenance_depth_two_reaches_the_next_level(self):
        items = self.paths(provenance_depth=2)
        self.assertIn("provenance", items["plots/map.html"])

    def test_provenance_depth_below_one_is_rejected(self):
        with self.assertRaises(ValueError):
            list_artifacts(self.chat_id, provenance_depth=0)

    def test_unchanged_artifact_is_not_read_again(self):
        self.paths(provenance_depth=None)
        with patch.object(artifacts_utils, "provenance_for_html") as read:
            items = self.paths(provenance_depth=None)
        read.assert_not_called()
        self.assertEqual(items["plots/map.html"]["provenance"], ["dynamical-fetch", "plot"])

    def test_rewritten_artifact_is_read_again(self):
        self.paths(provenance_depth=None)
        page = self.artifacts / self.chat_id / "plots" / "map.html"
        page.write_text(_page_with_provenance().replace("dynamical-fetch", "chirps-fetch"))
        self.assertEqual(self.paths(provenance_depth=None)["plots/map.html"]["provenance"], ["chirps-fetch", "plot"])

    def test_restamped_zarr_store_is_read_again(self):
        store = self.artifacts / self.chat_id / "plots" / "a.zarr"
        store.mkdir()

        def stamp(chain):
            attrs = {"weather_skills_history": json.dumps(chain)}
            (store / "zarr.json").write_text(json.dumps({"attributes": attrs}))

        stamp(CHAIN)
        self.assertEqual(self.paths(provenance_depth=None)["plots/a.zarr"]["provenance"], ["dynamical-fetch", "plot"])
        stamp(CHAIN[:1])
        self.assertEqual(self.paths(provenance_depth=None)["plots/a.zarr"]["provenance"], ["dynamical-fetch"])

    def test_depth_below_one_is_rejected(self):
        with self.assertRaises(ValueError):
            list_artifacts(self.chat_id, depth=0)

    def test_async_listing_runs_on_a_worker_thread(self):
        seen = {}
        real = artifacts_utils.list_artifacts

        def spy(*args, **kwargs):
            seen["thread"] = threading.current_thread()
            return real(*args, **kwargs)

        async def run():
            seen["loop_thread"] = threading.current_thread()
            return await list_artifacts_async(self.chat_id, depth=1, provenance=False)

        with patch.object(artifacts_utils, "list_artifacts", spy):
            entries = asyncio.run(run())
        self.assertIsNot(seen["thread"], seen["loop_thread"])
        self.assertEqual({e["path"] for e in entries}, self.top)


class ArtifactsRouteOptionsTest(SandboxCase):
    def setUp(self):
        super().setUp()
        self.route_patches = [
            patch("open_webui.utils.organizations.Chats", MagicMock(**{"is_live_share.return_value": False})),
            patch("open_webui.utils.organizations.can_read_chat", return_value=True),
        ]
        for p in self.route_patches:
            p.start()
        app = FastAPI()
        app.include_router(artifacts_router.router, prefix="/api/v1/chats")
        app.dependency_overrides[get_verified_user] = lambda: MagicMock(id="u1")
        self.client = TestClient(app)

    def tearDown(self):
        for p in self.route_patches:
            p.stop()
        super().tearDown()

    def url(self, query: str = "") -> str:
        return f"/api/v1/chats/{self.chat_id}/artifacts{query}"

    def test_default_is_the_full_tree_with_top_level_provenance(self):
        res = self.client.get(self.url())
        self.assertEqual(res.status_code, 200)
        items = {i["path"]: i for i in res.json()}
        self.assertIn("runs/2024/day1/out.csv", items)
        self.assertIn("provenance", items["summary.html"])
        self.assertNotIn("provenance", items["plots/map.html"])

    def test_depth_and_provenance_query(self):
        res = self.client.get(self.url("?depth=2&provenance=false"))
        self.assertEqual(res.status_code, 200)
        items = {i["path"]: i for i in res.json()}
        self.assertNotIn("runs/2024/day1", items)
        self.assertTrue(items["runs/2024"]["truncated"])
        self.assertNotIn("provenance", items["plots/map.html"])

    def test_depth_below_one_is_a_validation_error(self):
        self.assertEqual(self.client.get(self.url("?depth=0")).status_code, 422)

    def test_unreadable_chat_is_refused(self):
        with patch("open_webui.utils.organizations.can_read_chat", return_value=False):
            self.assertEqual(self.client.get(self.url()).status_code, 401)


class ListArtifactsToolOptionsTest(SandboxCase):
    def call(self, **kwargs) -> str:
        with (
            patch("open_webui.utils.builtin_tools.Users"),
            patch("open_webui.utils.builtin_tools.Chats"),
            patch("open_webui.utils.builtin_tools.can_read_chat", return_value=True),
        ):
            return list_artifacts_tool(
                __user__={"id": "u1"},
                __metadata__={"chat_id": self.chat_id},
                **kwargs,
            )

    def test_depth_marks_unexpanded_folders(self):
        out = self.call(depth=1)
        self.assertIn("`runs/` (directory, not expanded)", out)
        self.assertNotIn("runs/2024", out)
        self.assertIn("list one by passing it as `path`", out)

    def test_default_lists_every_level(self):
        out = self.call()
        self.assertIn("`runs/2024/day1/out.csv`", out)
        self.assertNotIn("not expanded", out)

    def test_path_lists_only_that_subtree(self):
        out = self.call(path="runs")
        self.assertIn("- `runs/` (directory)", out)
        self.assertIn("`runs/2024/day1/out.csv`", out)
        self.assertNotIn("notes.csv", out)

    def test_provenance_is_off_by_default_and_shown_on_request(self):
        self.assertNotIn("made by", self.call())
        self.assertIn("made by: dynamical-fetch → plot", self.call(provenance=True))

    def test_provenance_covers_only_the_folder_asked_about(self):
        out = self.call(provenance=True)
        line = lambda path: next(l for l in out.splitlines() if f"`{path}`" in l)
        self.assertIn("made by: dynamical-fetch → plot", line("summary.html"))
        self.assertNotIn("made by", line("plots/map.html"))
        self.assertIn(
            "made by: dynamical-fetch → plot",
            next(l for l in self.call(path="plots", provenance=True).splitlines() if "map.html" in l),
        )

    def test_depth_below_one(self):
        self.assertIn("depth must be at least 1", self.call(depth=0))

    def test_file_path_reports_the_file(self):
        self.assertIn("`notes.csv` (file, 4 bytes)", self.call(path="notes.csv"))


if __name__ == "__main__":
    unittest.main()
