"""Per-user skill pack install helpers."""

from __future__ import annotations

import unittest

from open_webui.utils.skills import pack_dirname


class PackDirnameTest(unittest.TestCase):
    def test_same_url_ref_differs_by_owner(self):
        url = "https://github.com/org/repo.git"
        a = pack_dirname(url, "main", owner_key="user-aaa")
        b = pack_dirname(url, "main", owner_key="user-bbb")
        self.assertNotEqual(a, b)
        self.assertTrue(a.startswith("repo__main__"))
        self.assertTrue(b.startswith("repo__main__"))

    def test_without_owner_is_stable(self):
        url = "https://github.com/org/repo.git"
        self.assertEqual(pack_dirname(url, "main"), "repo__main")


if __name__ == "__main__":
    unittest.main()
