import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("prewarm_uv_cache", HERE / "prewarm_uv_cache.py")
prewarm = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prewarm)


class SkillScriptsTest(TestCase):
    def test_finds_pep723_scripts_and_skips_tests(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill = root / "skills" / "plot" / "scripts"
            skill.mkdir(parents=True)
            (skill / "plot.py").write_text("# /// script\n# dependencies = [\"xarray\"]\n# ///\n")
            (skill / "notes.py").write_text("print('not a skill')\n")
            tests = root / "skills" / "plot" / "tests"
            tests.mkdir()
            (tests / "test_plot.py").write_text("# /// script\n# dependencies = [\"pytest\"]\n# ///\n")
            found = [p.relative_to(root).as_posix() for p in prewarm.skill_scripts(root / "skills")]
        self.assertEqual(found, ["skills/plot/scripts/plot.py"])
