#!/usr/bin/env python3
"""Smoke test for skill packs (run inside the app container)."""
import asyncio
import shutil
from pathlib import Path

from open_webui.env import SKILLS_DIR, UV_CACHE_DIR
from open_webui.models.skill_packs import SkillPacks
from open_webui.models.tools import Tools
from open_webui.utils.artifacts import chat_sandbox
from open_webui.utils.plugin import load_tool_module_by_id, replace_imports
from open_webui.utils.skill_runtime import run_skill
from open_webui.utils.skills import (
    discover_skills,
    generate_tool_content,
    skill_method_name,
    sync_pack_tools,
    validate_public_git_url,
)
from open_webui.utils.tools import get_tool_specs


def main():
    print("SKILLS_DIR", SKILLS_DIR)
    print("UV_CACHE_DIR", UV_CACHE_DIR)
    assert SKILLS_DIR.exists() and UV_CACHE_DIR.exists()

    root = Path("/tmp/hello-skill-pack/hello-skill")
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    (root / "SKILL.md").write_text(
        """---
name: hello-skill
description: Tiny fixture skill that echoes argv and writes a file.
metadata:
  version: "0.0.1"
---

# hello-skill

## Usage

```
uv run --script ${CLAUDE_SKILL_DIR}/scripts/hello.py --message hi --output out.txt
```
""",
        encoding="utf-8",
    )
    (root / "scripts" / "hello.py").write_text(
        "# /// script\n"
        '# requires-python = ">=3.11"\n'
        "# dependencies = []\n"
        "# ///\n"
        "import argparse\n"
        "from pathlib import Path\n"
        "parser = argparse.ArgumentParser()\n"
        'parser.add_argument("--message", default="hello")\n'
        'parser.add_argument("--output", "-o", required=True)\n'
        "args = parser.parse_args()\n"
        'Path(args.output).write_text(args.message + "\\n", encoding="utf-8")\n'
        'print(f"wrote {args.output}: {args.message}")\n',
        encoding="utf-8",
    )

    found = discover_skills(Path("/tmp/hello-skill-pack"))
    assert len(found) == 1 and found[0].name == "hello-skill", found
    print("discover-ok", found[0].version)

    content = generate_tool_content(
        method_name=skill_method_name(found[0].name),
        skill_name=found[0].name,
        description=found[0].description,
        usage=found[0].usage,
        skill_dir=found[0].skill_dir,
        version=found[0].version,
    )
    content = replace_imports(content)
    module, _ = load_tool_module_by_id("skill_hello_skill_smoke", content=content)
    specs = get_tool_specs(module)
    assert specs and specs[0]["name"] == "hello_skill", specs
    props = specs[0]["parameters"]["properties"]
    assert "argv" in props and "script" in props and "env_secrets" in props, props
    print("specs-ok", specs[0]["name"], list(props))

    pack_dir = SKILLS_DIR / "fixture_hello__main"
    if pack_dir.exists():
        shutil.rmtree(pack_dir)
    shutil.copytree("/tmp/hello-skill-pack", pack_dir)

    for p in SkillPacks.get_all():
        if p.git_url.endswith("fixture-hello.git") or "fixture_hello" in p.local_path:
            for s in (p.meta or {}).get("skills") or []:
                tid = s.get("tool_id")
                if tid:
                    Tools.delete_tool_by_id(tid)
            SkillPacks.delete(p.id)
    if Tools.get_tool_by_id("skill_hello_skill"):
        Tools.delete_tool_by_id("skill_hello_skill")

    pack = SkillPacks.insert(
        "smoke-admin",
        name="fixture-hello@main",
        git_url="https://example.com/fixture-hello.git",
        git_ref="main",
        commit_sha="deadbeef",
        local_path=str(pack_dir),
        meta={"skills": []},
    )
    tools_cache = {}
    pack = sync_pack_tools(pack, tools_cache, user_id="smoke-admin")
    assert pack.skills and pack.skills[0].tool_id, pack
    tool_id = pack.skills[0].tool_id
    tool = Tools.get_tool_by_id(tool_id)
    assert tool and tool.meta.manifest.get("kind") == "skill", tool.meta
    print("sync-ok", tool_id, tool.meta.manifest.get("version"))

    chat_id = "smoke-skill-chat"
    sandbox = chat_sandbox(chat_id)
    skill_dir = pack.skills[0].skill_dir or str(pack_dir / "hello-skill")
    result = asyncio.run(
        run_skill(
            skill_dir,
            argv=["--message", "weather-skills", "--output", "hello-out.txt"],
            __metadata__={"chat_id": chat_id},
        )
    )
    print(result)
    assert isinstance(result, dict), result
    assert result.get("ok") is True, result
    assert "weather-skills" in (result.get("stdout") or ""), result
    out = sandbox / "hello-out.txt"
    assert out.exists() and out.read_text().strip() == "weather-skills", out
    print("run-skill-ok", out)

    bad = asyncio.run(
        run_skill(
            skill_dir,
            argv=["--message", "x", "--output", "bad.txt"],
            env_secrets=["not-a-valid-name!"],
            __metadata__={"chat_id": chat_id},
        )
    )
    assert bad.get("ok") is False and "Invalid env_secrets" in (bad.get("stderr") or ""), bad
    print("env-secrets-reject-ok")

    try:
        validate_public_git_url("git@github.com:x/y.git")
        raise SystemExit("expected https-only failure")
    except Exception as e:
        print("url-reject-ok", str(e)[:80])

    # Call through generated Tools callable like middleware would
    callable_result = asyncio.run(
        module.hello_skill(
            argv=["--message", "via-tool", "--output", "via-tool.txt"],
            env_secrets=[],
            __metadata__={"chat_id": chat_id},
        )
    )
    print(callable_result)
    assert (sandbox / "via-tool.txt").read_text().strip() == "via-tool"
    print("tool-callable-ok")
    print("ALL-SMOKE-OK")


if __name__ == "__main__":
    main()
