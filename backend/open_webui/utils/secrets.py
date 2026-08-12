import ast
import copy
import json
import logging
import re
from typing import Any, Optional

from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.secrets import Secret, Secrets
from open_webui.models.teams import Teams
from open_webui.models.users import UserModel
from open_webui.utils.teams import is_team_admin, is_team_member, user_team_ids

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MAIN"])

SECRET_PLACEHOLDER_RE = re.compile(r"\{\{\s*secret:([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


def can_manage_secret(user: UserModel, row: Optional[Secret]) -> bool:
    if row is None:
        return False
    if user.role == "admin":
        return True
    if row.team_id:
        return is_team_admin(row.team_id, user.id, user.role)
    return row.user_id == user.id


def can_use_secret(user: UserModel, row: Optional[Secret]) -> bool:
    if row is None:
        return False
    if user.role == "admin":
        return True
    if row.team_id:
        return is_team_member(row.team_id, user.id)
    return row.user_id == user.id


def list_secret_metadata(user: UserModel) -> list[dict]:
    personal = Secrets.list_personal(user.id)
    team_ids = user_team_ids(user.id)
    if user.role == "admin":
        team_ids = list({*team_ids, *[t.id for t in Teams.get_all_teams()]})
    team_rows = Secrets.list_teams(team_ids)
    team_names = {t.id: t.name for t in Teams.get_all_teams()} if team_rows else {}

    personal_names = {row.name for row in personal}
    items = []
    for row in personal:
        items.append(
            {
                **row.model_dump(),
                "scope": "personal",
                "can_manage": True,
                "overridden": False,
            }
        )
    for row in team_rows:
        items.append(
            {
                **row.model_dump(),
                "scope": "team",
                "team_name": team_names.get(row.team_id),
                "can_manage": is_team_admin(row.team_id, user.id, user.role),
                "overridden": row.name in personal_names,
            }
        )
    return items


def list_secret_names(user: UserModel) -> list[str]:
    seen = []
    for item in list_secret_metadata(user):
        if item["name"] not in seen:
            seen.append(item["name"])
    return seen


def _resolve_row(user: UserModel, name: str) -> Optional[Secret]:
    # Personal always wins over a team secret with the same name.
    personal = Secrets.get_personal(user.id, name)
    if personal:
        return personal
    team_ids = user_team_ids(user.id)
    matches = []
    for team_id in team_ids:
        row = Secrets.get_team(team_id, name)
        if row:
            matches.append(row)
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError(
            f"Secret '{name}' exists on multiple teams; rename one so the name is unique"
        )
    if user.role == "admin":
        # App admins may reference any team secret by unique name.
        all_matches = [
            Secrets.get_team(team.id, name) for team in Teams.get_all_teams()
        ]
        all_matches = [m for m in all_matches if m]
        if len(all_matches) == 1:
            return all_matches[0]
        if len(all_matches) > 1:
            raise ValueError(
                f"Secret '{name}' exists on multiple teams; rename one so the name is unique"
            )
    return None


def resolve_secret_value(user: UserModel, name: str) -> str:
    row = _resolve_row(user, name)
    if not row or not can_use_secret(user, row):
        raise ValueError(f"Unknown secret: {name}")
    return Secrets.decrypt(row)


def substitute_secrets(value: Any, user: UserModel, used: Optional[dict] = None) -> Any:
    """Replace {{secret:NAME}} placeholders. Mutates a copy, not the original."""
    if used is None:
        used = {}

    if isinstance(value, str):
        def repl(match: re.Match) -> str:
            name = match.group(1)
            plaintext = resolve_secret_value(user, name)
            used[name] = plaintext
            return plaintext

        return SECRET_PLACEHOLDER_RE.sub(repl, value)
    if isinstance(value, dict):
        return {k: substitute_secrets(v, user, used) for k, v in value.items()}
    if isinstance(value, list):
        return [substitute_secrets(v, user, used) for v in value]
    return value


def substitute_tool_params(params: dict, user: UserModel) -> tuple[dict, dict]:
    used: dict = {}
    resolved = substitute_secrets(copy.deepcopy(params), user, used)
    return resolved, used


def contains_secret_placeholder(value: Any) -> bool:
    if isinstance(value, str):
        return bool(SECRET_PLACEHOLDER_RE.search(value))
    if isinstance(value, dict):
        return any(contains_secret_placeholder(v) for v in value.values())
    if isinstance(value, list):
        return any(contains_secret_placeholder(v) for v in value)
    return False


def apply_secrets_for_tool(
    params: dict, user: UserModel, *, direct: bool
) -> tuple[dict, dict]:
    """Decrypt placeholders only for server-side tools.

    Client/direct tools run in the browser, so they keep the raw
    placeholder and never receive plaintext.
    """
    if direct:
        if contains_secret_placeholder(params):
            raise ValueError(
                "Secrets cannot be sent to client-side tools. "
                "Use a server-side tool so values stay on the server."
            )
        return params, {}
    return substitute_tool_params(params, user)


def redact_secrets(text: Any, used: dict) -> Any:
    """Replace known plaintext secret values with placeholders."""
    if not used:
        return text
    if not isinstance(text, str):
        if isinstance(text, dict):
            return {k: redact_secrets(v, used) for k, v in text.items()}
        if isinstance(text, list):
            return [redact_secrets(v, used) for v in text]
        return text
    # Longest first so overlapping values redact cleanly.
    for name, plaintext in sorted(used.items(), key=lambda item: -len(item[1] or "")):
        if plaintext:
            text = text.replace(plaintext, f"{{{{secret:{name}}}}}")
    return text


def secret_usage_hint(user: UserModel) -> str:
    names = list_secret_names(user)
    hint = (
        "If the user provides a credential, API key, token, or password to store, "
        "call create_secret with a name and the value. After it is saved, never "
        "repeat the raw value in your reply or in later tool arguments — use "
        "{{secret:NAME}} instead; the server substitutes it before the tool runs. "
        "For skill tools that read credentials from the environment, pass "
        'env_secrets=["NAME"] so the secret is injected as an env var with the '
        "same name (preferred over putting placeholders in argv). "
        "If a personal secret and a team secret share a name, the personal value is used."
    )
    if names:
        placeholders = ", ".join(f"{{{{secret:{n}}}}}" for n in names)
        hint = f"{hint} Available secrets: {placeholders}."
    return hint


def parse_tool_arguments(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    if not isinstance(raw, str):
        return {}
    try:
        parsed = ast.literal_eval(raw)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}


def sensitive_values_from_params(tool_name: str, params: dict) -> dict:
    """Plaintext written into a tool (e.g. create_secret) so it can be redacted."""
    used = {}
    if tool_name == "create_secret" and isinstance(params, dict):
        name = (params.get("name") or "secret").strip() or "secret"
        value = params.get("value")
        if value:
            used[name] = value
    return used


def _scrubbed_params(tool_name: str, params: dict) -> dict:
    out = copy.deepcopy(params)
    if tool_name == "create_secret" and "value" in out:
        name = (out.get("name") or "NAME").strip() or "NAME"
        out["value"] = f"{{{{secret:{name}}}}}"
    return out


def display_tool_arguments(tool_name: str, arguments: Any) -> Any:
    """Arguments safe to show in the UI or send back to the model."""
    if tool_name != "create_secret":
        return arguments
    if isinstance(arguments, dict):
        return _scrubbed_params(tool_name, arguments)
    params = parse_tool_arguments(arguments)
    if not params:
        return arguments
    return json.dumps(_scrubbed_params(tool_name, params))


def scrub_tool_call_in_place(tool_call: dict) -> dict:
    """Return real params, then replace sensitive fields on the stored call."""
    if not isinstance(tool_call, dict):
        return {}

    fn = tool_call.get("function")
    if isinstance(fn, dict):
        params = parse_tool_arguments(fn.get("arguments", "{}"))
        fn["arguments"] = json.dumps(_scrubbed_params(fn.get("name", ""), params))
        return params

    params = tool_call.get("parameters") or {}
    if isinstance(params, dict):
        real = copy.deepcopy(params)
        tool_call["parameters"] = _scrubbed_params(tool_call.get("name", ""), params)
        return real
    return {}
