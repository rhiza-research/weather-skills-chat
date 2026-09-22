import ast
import copy
import json
import logging
import re
from typing import Any, Optional

from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.secrets import Secret, Secrets
from open_webui.models.users import UserModel
from open_webui.utils.organizations import is_member, is_org_admin, is_personal_org

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MAIN"])

SECRET_PLACEHOLDER_RE = re.compile(r"\{\{\s*secret:([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


def can_manage_secret(user: UserModel, row: Optional[Secret]) -> bool:
    if row is None:
        return False
    if row.visibility == "private":
        return row.user_id == user.id
    return is_org_admin(row.organization_id, user.id) or row.user_id == user.id


def can_use_secret(user: UserModel, row: Optional[Secret]) -> bool:
    if row is None:
        return False
    if row.visibility == "private":
        return row.user_id == user.id
    return is_member(row.organization_id, user.id)


def list_secret_metadata(
    user: UserModel, organization_id: str
) -> list[dict]:
    from open_webui.utils.chat_timing import log_timing
    import time as _time

    t0 = _time.perf_counter()
    items = []
    for row in Secrets.list_for_org(organization_id, user.id):
        items.append(
            {
                **row.model_dump(),
                "scope": "organization" if row.visibility == "organization" else "private",
                "can_manage": can_manage_secret(user, Secrets.get_by_id(row.id)),
                "overridden": False,
            }
        )
    private_names = {
        item["name"] for item in items if item["visibility"] == "private"
    }
    for item in items:
        if item["visibility"] == "organization":
            item["overridden"] = item["name"] in private_names
    log_timing(
        "db.list_secret_metadata",
        _time.perf_counter() - t0,
        n=len(items),
        user_id=user.id,
    )
    return items


def _resolve_row(user: UserModel, name: str, organization_id: str) -> Optional[Secret]:
    personal = Secrets.get_private(organization_id, user.id, name)
    if personal:
        return personal
    return Secrets.get_shared(organization_id, name)


def resolve_secret_value(
    user: UserModel, name: str, organization_id: Optional[str] = None
) -> str:
    organization_id = organization_id or user.id
    row = _resolve_row(user, name, organization_id)
    if not row or not can_use_secret(user, row):
        raise ValueError(f"Unknown secret: {name}")
    return Secrets.decrypt(row)


def substitute_secrets(
    value: Any,
    user: UserModel,
    used: Optional[dict] = None,
    organization_id: Optional[str] = None,
) -> Any:
    if used is None:
        used = {}
    organization_id = organization_id or user.id

    if isinstance(value, str):
        def repl(match: re.Match) -> str:
            name = match.group(1)
            plaintext = resolve_secret_value(user, name, organization_id)
            used[name] = plaintext
            return plaintext

        return SECRET_PLACEHOLDER_RE.sub(repl, value)
    if isinstance(value, dict):
        return {
            k: substitute_secrets(v, user, used, organization_id)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [substitute_secrets(v, user, used, organization_id) for v in value]
    return value


def substitute_tool_params(
    params: dict, user: UserModel, organization_id: Optional[str] = None
) -> tuple[dict, dict]:
    used: dict = {}
    resolved = substitute_secrets(
        copy.deepcopy(params), user, used, organization_id
    )
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
    params: dict,
    user: UserModel,
    *,
    direct: bool,
    organization_id: Optional[str] = None,
) -> tuple[dict, dict]:
    if direct:
        if contains_secret_placeholder(params):
            raise ValueError(
                "Secrets cannot be sent to client-side tools. "
                "Use a server-side tool so values stay on the server."
            )
        return params, {}
    return substitute_tool_params(params, user, organization_id)


def redact_secrets(text: Any, used: dict) -> Any:
    if not used:
        return text
    if not isinstance(text, str):
        if isinstance(text, dict):
            return {k: redact_secrets(v, used) for k, v in text.items()}
        if isinstance(text, list):
            return [redact_secrets(v, used) for v in text]
        return text
    for name, plaintext in sorted(used.items(), key=lambda item: -len(item[1] or "")):
        if plaintext:
            text = text.replace(plaintext, f"{{{{secret:{name}}}}}")
    return text


def secret_usage_hint(user: UserModel, organization_id: Optional[str] = None) -> str:
    organization_id = organization_id or user.id
    names = [item["name"] for item in list_secret_metadata(user, organization_id)]
    hint = (
        "If the user provides a credential, API key, token, or password to store, "
        "call create_secret with a name and the value. After it is saved, never "
        "repeat the raw value in your reply or in later tool arguments — use "
        "{{secret:NAME}} instead; the server substitutes it before the tool runs. "
        "For skill tools that read credentials from the environment, pass "
        'env_secrets=["NAME"] so the secret is injected as an env var with the '
        "same name (preferred over putting placeholders in argv). "
        "Private secrets in this organization override organization-shared secrets "
        "with the same name."
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
    if tool_name != "create_secret":
        return arguments
    if isinstance(arguments, dict):
        return _scrubbed_params(tool_name, arguments)
    params = parse_tool_arguments(arguments)
    if not params:
        return arguments
    return json.dumps(_scrubbed_params(tool_name, params))


def scrub_tool_call_in_place(tool_call: dict) -> dict:
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
