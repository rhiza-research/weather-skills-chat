"""Send skills on demand: the model reads a skill's instructions with
``read_skill`` and runs it with ``run_skill``.

Both tools are fixed for the chat, so the tool list never changes and the
prompt cache is kept; a skill's instructions arrive as a tool result at the end
of the conversation. Skills stay in the chat's tools for execution.
"""

import difflib

READ_SKILL = "read_skill"
RUN_SKILL = "run_skill"

READ_SKILL_SPEC = {
    "name": READ_SKILL,
    "description": (
        "Read skills' instructions before running them. Every skill this chat has "
        "is listed in the system prompt; name all the skills you need in one call."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "names": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Skill names, e.g. ['imerg_fetch', 'plot']",
            }
        },
        "required": ["names"],
    },
}


def _builtin(fn, spec: dict) -> dict:
    return {
        "toolkit_id": "builtin",
        "callable": fn,
        "spec": spec,
        "pydantic_model": None,
        "file_handler": False,
        "citation": False,
    }


def add_skill_tools(tools_dict: dict) -> set[str]:
    """Add ``read_skill`` and ``run_skill``; return the skills they serve."""
    # Only skills share one schema; tool servers and workspace tools keep their own.
    skills = {name for name, tool in tools_dict.items() if tool.get("kind") == "skill"}
    if not skills:
        return skills

    def unknown(name: str) -> str:
        close = difflib.get_close_matches(name or "", sorted(skills), n=3)
        hint = f" Did you mean {', '.join(close)}?" if close else ""
        return f"No skill `{name}` in this chat.{hint} Skills it has are listed in the system prompt."

    async def read_skill(names: list[str] = [], **_ignored) -> str:
        names = [names] if isinstance(names, str) else names or [""]
        return "\n\n".join(
            f"## {name}\n{(tools_dict[name]['spec'].get('description') or '').strip()}"
            if name in skills
            else unknown(name)
            for name in names
        )

    async def run_skill(skill: str = "", **kwargs):
        if skill not in skills:
            return unknown(skill)
        return await tools_dict[skill]["callable"](**kwargs)

    # Every skill takes the same arguments; run_skill adds which skill to run.
    params = tools_dict[min(skills)]["spec"].get("parameters") or {}
    run_spec = {
        "name": RUN_SKILL,
        "description": "Run a skill. Read its instructions with read_skill first; argv follows its usage.",
        "parameters": {
            **params,
            "properties": {
                "skill": {"type": "string", "description": "Skill name, e.g. 'plot'"},
                **(params.get("properties") or {}),
            },
            "required": ["skill", *(params.get("required") or [])],
        },
    }
    tools_dict[READ_SKILL] = _builtin(read_skill, READ_SKILL_SPEC)
    tools_dict[RUN_SKILL] = _builtin(run_skill, run_spec)
    return skills


def call_name(name: str, params: dict) -> str:
    """A ``run_skill`` call goes by its skill's name (``depends_on``, traces)."""
    return params.get("skill") or name if name == RUN_SKILL else name
