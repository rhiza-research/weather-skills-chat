import inspect
import logging
import re
import inspect
import aiohttp
import asyncio
import yaml

from pydantic import BaseModel
from pydantic.fields import FieldInfo
from typing import (
    Any,
    Awaitable,
    Callable,
    get_type_hints,
    get_args,
    get_origin,
    Dict,
    List,
    Tuple,
    Union,
    Optional,
    Type,
)
from functools import update_wrapper, partial


from fastapi import Request
from pydantic import BaseModel, Field, create_model

from langchain_core.utils.function_calling import (
    convert_to_openai_function as convert_pydantic_model_to_openai_function_spec,
)


from open_webui.models.tools import ToolCatalogModel, Tools
from open_webui.models.users import UserModel
from open_webui.utils.access_control import user_owns_or_has_access
from open_webui.utils.plugin import load_tool_module_by_id
from open_webui.utils.skill_version import (
    register_tool_by_function_name,
    resolve_tool_ids_by_skill_version,
    tool_version_from_record,
)
from open_webui.utils.tool_surfaces import (
    INTERFACE_ONLY,
    SURFACES_KEY,
    Surface,
    published_to,
    surfaces_for_tool_record,
)
from open_webui.env import AIOHTTP_CLIENT_TIMEOUT_TOOL_SERVER_DATA
from open_webui.utils.chat_timing import log_timing

import copy
import time

log = logging.getLogger(__name__)


def get_async_tool_function_and_apply_extra_params(
    function: Callable, extra_params: dict
) -> Callable[..., Awaitable]:
    sig = inspect.signature(function)
    extra_params = {k: v for k, v in extra_params.items() if k in sig.parameters}
    partial_func = partial(function, **extra_params)

    if inspect.iscoroutinefunction(function):
        update_wrapper(partial_func, function)
        return partial_func
    else:
        # Make it a coroutine function
        async def new_function(*args, **kwargs):
            return partial_func(*args, **kwargs)

        update_wrapper(new_function, function)
        return new_function


def _tool_manifest(tool) -> dict:
    meta = getattr(tool, "meta", None)
    if meta is None:
        return {}
    manifest = getattr(meta, "manifest", None)
    if manifest is None and isinstance(meta, dict):
        manifest = meta.get("manifest")
    return manifest if isinstance(manifest, dict) else {}


def _user_tool_valves(user: UserModel, tool_id: str) -> dict:
    settings = getattr(user, "settings", None)
    if not settings:
        return {}
    dumped = settings.model_dump() if hasattr(settings, "model_dump") else dict(settings)
    valves = ((dumped.get("tools") or {}).get("valves") or {}).get(tool_id)
    return valves if isinstance(valves, dict) else {}


def accessible_skill_records(
    user: UserModel,
    organization_id: Optional[str] = None,
    catalog: Optional[list[ToolCatalogModel]] = None,
) -> list[dict]:
    """Skill tools the user can use, for version-preference substitution."""
    from open_webui.models.org_catalog import OrgCatalogOverrides
    from open_webui.models.organizations import Organizations
    from open_webui.models.skill_packs import SkillPacks
    from open_webui.utils.catalog import skill_is_usable

    t0 = time.perf_counter()
    org_ids = (
        [organization_id]
        if organization_id
        else Organizations.user_organization_ids(user.id)
    )
    overrides = OrgCatalogOverrides.for_organizations(org_ids)
    visible_tool_ids = set()
    for pack in SkillPacks.get_all():
        for oid in org_ids:
            if not oid:
                continue
            for skill in (pack.meta or {}).get("skills") or []:
                if not isinstance(skill, dict) or not skill.get("tool_id"):
                    continue
                if skill_is_usable(oid, pack, skill, overrides):
                    visible_tool_ids.add(skill["tool_id"])

    tools = catalog if catalog is not None else Tools.get_tool_catalog()
    records = []
    for tool in tools:
        if tool.id not in visible_tool_ids:
            continue
        manifest = _tool_manifest(tool)
        if manifest.get("kind") != "skill":
            continue
        name = manifest.get("skill_name")
        if not name:
            continue
        records.append(
            {
                "id": tool.id,
                "skill_name": name,
                "version": manifest.get("version"),
                "enabled": True,
            }
        )
    log_timing(
        "db.accessible_skill_records",
        time.perf_counter() - t0,
        n=len(records),
        user_id=user.id,
        catalog=len(tools),
    )
    return records


def accessible_tool_ids(
    user: UserModel,
    organization_id: Optional[str] = None,
    catalog: Optional[list[ToolCatalogModel]] = None,
) -> list[str]:
    """Tool/skill IDs the user can use in this organization (automation default).

    Skill listing follows org-admin enablement (catalog default only seeds
    that toggle). Chat can still send explicit IDs.
    """
    tools = catalog if catalog is not None else Tools.get_tool_catalog()
    usable_skill_ids = {
        record["id"]
        for record in accessible_skill_records(user, organization_id, catalog=tools)
    }

    ids: list[str] = []
    for tool in tools:
        manifest = (tool.meta.manifest if tool.meta else None) or {}
        if manifest.get("kind") == "skill":
            if tool.id not in usable_skill_ids:
                continue
        elif not user_owns_or_has_access(
            user.id, tool.user_id, tool.access_control, "read", user.role
        ):
            continue
        ids.append(tool.id)
    return ids


def get_tools(
    request: Request,
    tool_ids: list[str],
    user: UserModel,
    extra_params: dict,
    catalog: Optional[list[ToolCatalogModel]] = None,
) -> dict[str, dict]:
    tools_dict = {}
    t0 = time.perf_counter()
    if catalog is None:
        catalog = Tools.get_tool_catalog()
    raw_org = None
    headers = getattr(request, "headers", None)
    if headers is not None:
        raw_org = headers.get("X-Organization-Id")
    org_id = raw_org.strip() if isinstance(raw_org, str) and raw_org.strip() else None
    t_resolve = time.perf_counter()
    skill_records = accessible_skill_records(
        user, organization_id=org_id, catalog=catalog
    )
    usable_skill_ids = {record["id"] for record in skill_records}
    tool_ids = resolve_tool_ids_by_skill_version(list(tool_ids), skill_records)
    resolve_s = time.perf_counter() - t_resolve
    by_id = {tool.id: tool for tool in catalog}

    load_s = 0.0
    valves_s = 0.0
    cache_hits = 0
    cache_misses = 0

    for tool_id in tool_ids:
        tool = by_id.get(tool_id)
        if tool is not None:
            manifest = _tool_manifest(tool)
            if manifest.get("kind") == "skill" and tool_id not in usable_skill_ids:
                continue
        if tool is None:
            if tool_id.startswith("server:"):
                server_idx = int(tool_id.split(":")[1])
                tool_server_connection = (
                    request.app.state.config.TOOL_SERVER_CONNECTIONS[server_idx]
                )
                server_acl = tool_server_connection.get("config", {}).get(
                    "access_control", None
                )
                if not user_owns_or_has_access(
                    user.id, f"server:{server_idx}", server_acl, "read", user.role
                ):
                    continue
                tool_server_data = None
                for server in request.app.state.TOOL_SERVERS:
                    if server["idx"] == server_idx:
                        tool_server_data = server
                        break
                assert tool_server_data is not None
                specs = tool_server_data.get("specs", [])

                for spec in specs:
                    function_name = spec["name"]

                    auth_type = tool_server_connection.get("auth_type", "bearer")
                    token = None

                    if auth_type == "bearer":
                        token = tool_server_connection.get("key", "")
                    elif auth_type == "session":
                        token = request.state.token.credentials

                    def make_tool_function(function_name, token, tool_server_data):
                        async def tool_function(**kwargs):
                            log.debug("Executing tool function %s", function_name)
                            return await execute_tool_server(
                                token=token,
                                url=tool_server_data["url"],
                                name=function_name,
                                params=kwargs,
                                server_data=tool_server_data,
                            )

                        return tool_function

                    tool_function = make_tool_function(
                        function_name, token, tool_server_data
                    )

                    callable = get_async_tool_function_and_apply_extra_params(
                        tool_function,
                        {},
                    )

                    tool_dict = {
                        "tool_id": tool_id,
                        "callable": callable,
                        "spec": spec,
                        "version": None,
                        # Tool server operations are not published to the endpoint.
                        SURFACES_KEY: INTERFACE_ONLY,
                    }
                    register_tool_by_function_name(tools_dict, function_name, tool_dict)
            else:
                continue
        else:
            # Usable skills follow org enablement, not the installer's private ACL.
            if _tool_manifest(tool).get("kind") != "skill" and not user_owns_or_has_access(
                user.id, tool.user_id, tool.access_control, "read", user.role
            ):
                continue
            module = request.app.state.TOOLS.get(tool_id, None)
            if module is None:
                cache_misses += 1
                t_load = time.perf_counter()
                module, _ = load_tool_module_by_id(tool_id)
                load_s += time.perf_counter() - t_load
                request.app.state.TOOLS[tool_id] = module
            else:
                cache_hits += 1

            # A separate copy per tool, including __user__. The callables hold a reference to this
            # dict, so sharing one dict gave every tool the last tool's __id__ and user valves.
            tool_params = {
                **extra_params,
                "__id__": tool_id,
                "__user__": {**(extra_params.get("__user__") or {})},
            }

            # Set valves for the tool
            if hasattr(module, "valves") and hasattr(module, "Valves"):
                t_valves = time.perf_counter()
                valves = tool.valves if getattr(tool, "valves", None) else {}
                valves_s += time.perf_counter() - t_valves
                module.valves = module.Valves(**(valves or {}))
            if hasattr(module, "UserValves"):
                t_valves = time.perf_counter()
                tool_params["__user__"]["valves"] = module.UserValves(  # type: ignore
                    **_user_tool_valves(user, tool_id)
                )
                valves_s += time.perf_counter() - t_valves

            for spec in tool.specs:
                # TODO: Fix hack for OpenAI API
                # Some times breaks OpenAI but others don't. Leaving the comment
                for val in spec.get("parameters", {}).get("properties", {}).values():
                    if val.get("type") == "str":
                        val["type"] = "string"

                # Remove internal reserved parameters (e.g. __id__, __user__)
                spec["parameters"]["properties"] = {
                    key: val
                    for key, val in spec["parameters"]["properties"].items()
                    if not key.startswith("__")
                }

                # convert to function that takes only model params and inserts custom params
                function_name = spec["name"]
                tool_function = getattr(module, function_name)
                callable = get_async_tool_function_and_apply_extra_params(
                    tool_function, tool_params
                )

                # TODO: Support Pydantic models as parameters
                if callable.__doc__ and callable.__doc__.strip() != "":
                    s = re.split(":(param|return)", callable.__doc__, 1)
                    spec["description"] = s[0]
                else:
                    spec["description"] = function_name

                tool_dict = {
                    "tool_id": tool_id,
                    "callable": callable,
                    "spec": spec,
                    "version": tool_version_from_record(tool),
                    SURFACES_KEY: surfaces_for_tool_record(tool),
                    # Misc info
                    "metadata": {
                        "file_handler": hasattr(module, "file_handler")
                        and module.file_handler,
                        "citation": hasattr(module, "citation") and module.citation,
                    },
                }
                register_tool_by_function_name(tools_dict, function_name, tool_dict)

    log_timing(
        "get_tools",
        time.perf_counter() - t0,
        n_in=len(tool_ids),
        n_out=len(tools_dict),
        resolve_incl_accessible_s=f"{resolve_s:.3f}",
        catalog_n=len(catalog),
        load_module_s=f"{load_s:.3f}",
        valves_s=f"{valves_s:.3f}",
        cache_hits=cache_hits,
        cache_misses=cache_misses,
    )
    return tools_dict


def merged_catalog(
    request,
    tool_ids: list[str],
    user: UserModel,
    extra_params: dict,
    catalog: Optional[list[ToolCatalogModel]] = None,
) -> dict:
    """Built-in tools merged with the tools for tool_ids, keyed by function name.

    Used by both the chat loop and the MCP endpoint. A tool from tool_ids replaces a built-in with
    the same name. If the built-ins fail to load, the error is logged and only the tool_ids tools
    are returned.
    """
    from open_webui.utils.builtin_tools import get_builtin_tools

    generated = (
        get_tools(request, tool_ids, user, extra_params, catalog=catalog)
        if tool_ids
        else {}
    )
    try:
        builtins = get_builtin_tools(extra_params)
    except Exception:
        log.exception("Failed to load built-in tools")
        builtins = {}
    return {**builtins, **generated}


def interface_catalog(
    request,
    tool_ids: list[str],
    user: UserModel,
    extra_params: dict,
    catalog: Optional[list[ToolCatalogModel]] = None,
) -> dict:
    """merged_catalog filtered to entries published to the chat interface.

    Endpoint-only tools, such as get_artifact, are excluded from the chat model's tool list.
    """
    return published_to(
        merged_catalog(request, tool_ids, user, extra_params, catalog=catalog),
        Surface.INTERFACE,
    )


def parse_description(docstring: str | None) -> str:
    """
    Parse a function's docstring to extract the description.

    Args:
        docstring (str): The docstring to parse.

    Returns:
        str: The description.
    """

    if not docstring:
        return ""

    lines = [line.strip() for line in docstring.strip().split("\n")]
    description_lines: list[str] = []

    for line in lines:
        if re.match(r":param", line) or re.match(r":return", line):
            break

        description_lines.append(line)

    return "\n".join(description_lines)


def parse_docstring(docstring):
    """
    Parse a function's docstring to extract parameter descriptions in reST format.

    Args:
        docstring (str): The docstring to parse.

    Returns:
        dict: A dictionary where keys are parameter names and values are descriptions.
    """
    if not docstring:
        return {}

    # Regex to match `:param name: description` format
    param_pattern = re.compile(r":param (\w+):\s*(.+)")
    param_descriptions = {}

    for line in docstring.splitlines():
        match = param_pattern.match(line.strip())
        if not match:
            continue
        param_name, param_description = match.groups()
        if param_name.startswith("__"):
            continue
        param_descriptions[param_name] = param_description

    return param_descriptions


def convert_function_to_pydantic_model(func: Callable) -> type[BaseModel]:
    """
    Converts a Python function's type hints and docstring to a Pydantic model,
    including support for nested types, default values, and descriptions.

    Args:
        func: The function whose type hints and docstring should be converted.
        model_name: The name of the generated Pydantic model.

    Returns:
        A Pydantic model class.
    """
    type_hints = get_type_hints(func)
    signature = inspect.signature(func)
    parameters = signature.parameters

    docstring = func.__doc__

    description = parse_description(docstring)
    function_descriptions = parse_docstring(docstring)

    field_defs = {}
    for name, param in parameters.items():

        type_hint = type_hints.get(name, Any)
        default_value = param.default if param.default is not param.empty else ...

        description = function_descriptions.get(name, None)

        if description:
            field_defs[name] = type_hint, Field(default_value, description=description)
        else:
            field_defs[name] = type_hint, default_value

    model = create_model(func.__name__, **field_defs)
    model.__doc__ = description

    return model


def get_functions_from_tool(tool: object) -> list[Callable]:
    return [
        getattr(tool, func)
        for func in dir(tool)
        if callable(
            getattr(tool, func)
        )  # checks if the attribute is callable (a method or function).
        and not func.startswith(
            "__"
        )  # filters out special (dunder) methods like init, str, etc. — these are usually built-in functions of an object that you might not need to use directly.
        and not inspect.isclass(
            getattr(tool, func)
        )  # ensures that the callable is not a class itself, just a method or function.
    ]


def get_tool_specs(tool_module: object) -> list[dict]:
    function_models = map(
        convert_function_to_pydantic_model, get_functions_from_tool(tool_module)
    )

    specs = [
        convert_pydantic_model_to_openai_function_spec(function_model)
        for function_model in function_models
    ]

    return specs


def resolve_schema(schema, components):
    """
    Recursively resolves a JSON schema using OpenAPI components.
    """
    if not schema:
        return {}

    if "$ref" in schema:
        ref_path = schema["$ref"]
        ref_parts = ref_path.strip("#/").split("/")
        resolved = components
        for part in ref_parts[1:]:  # Skip the initial 'components'
            resolved = resolved.get(part, {})
        return resolve_schema(resolved, components)

    resolved_schema = copy.deepcopy(schema)

    # Recursively resolve inner schemas
    if "properties" in resolved_schema:
        for prop, prop_schema in resolved_schema["properties"].items():
            resolved_schema["properties"][prop] = resolve_schema(
                prop_schema, components
            )

    if "items" in resolved_schema:
        resolved_schema["items"] = resolve_schema(resolved_schema["items"], components)

    return resolved_schema


def convert_openapi_to_tool_payload(openapi_spec):
    """
    Converts an OpenAPI specification into a custom tool payload structure.

    Args:
        openapi_spec (dict): The OpenAPI specification as a Python dict.

    Returns:
        list: A list of tool payloads.
    """
    tool_payload = []

    for path, methods in openapi_spec.get("paths", {}).items():
        for method, operation in methods.items():
            tool = {
                "type": "function",
                "name": operation.get("operationId"),
                "description": operation.get(
                    "description", operation.get("summary", "No description available.")
                ),
                "parameters": {"type": "object", "properties": {}, "required": []},
            }

            # Extract path and query parameters
            for param in operation.get("parameters", []):
                param_name = param["name"]
                param_schema = param.get("schema", {})
                tool["parameters"]["properties"][param_name] = {
                    "type": param_schema.get("type"),
                    "description": param_schema.get("description", ""),
                }
                if param.get("required"):
                    tool["parameters"]["required"].append(param_name)

            # Extract and resolve requestBody if available
            request_body = operation.get("requestBody")
            if request_body:
                content = request_body.get("content", {})
                json_schema = content.get("application/json", {}).get("schema")
                if json_schema:
                    resolved_schema = resolve_schema(
                        json_schema, openapi_spec.get("components", {})
                    )

                    if resolved_schema.get("properties"):
                        tool["parameters"]["properties"].update(
                            resolved_schema["properties"]
                        )
                        if "required" in resolved_schema:
                            tool["parameters"]["required"] = list(
                                set(
                                    tool["parameters"]["required"]
                                    + resolved_schema["required"]
                                )
                            )
                    elif resolved_schema.get("type") == "array":
                        tool["parameters"] = resolved_schema  # special case for array

            tool_payload.append(tool)

    return tool_payload


async def get_tool_server_data(token: str, url: str) -> Dict[str, Any]:
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    error = None
    try:
        timeout = aiohttp.ClientTimeout(total=AIOHTTP_CLIENT_TIMEOUT_TOOL_SERVER_DATA)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers) as response:
                if response.status != 200:
                    error_body = await response.json()
                    raise Exception(error_body)

                # Check if URL ends with .yaml or .yml to determine format
                if url.lower().endswith((".yaml", ".yml")):
                    text_content = await response.text()
                    res = yaml.safe_load(text_content)
                else:
                    res = await response.json()
    except Exception as err:
        log.exception(f"Could not fetch tool server spec from {url}")
        if isinstance(err, dict) and "detail" in err:
            error = err["detail"]
        else:
            error = str(err)
        raise Exception(error)

    data = {
        "openapi": res,
        "info": res.get("info", {}),
        "specs": convert_openapi_to_tool_payload(res),
    }

    print("Fetched data:", data)
    return data


async def get_tool_servers_data(
    servers: List[Dict[str, Any]], session_token: Optional[str] = None
) -> List[Dict[str, Any]]:
    # Prepare list of enabled servers along with their original index
    server_entries = []
    for idx, server in enumerate(servers):
        if server.get("config", {}).get("enable"):
            url_path = server.get("path", "openapi.json")
            full_url = f"{server.get('url')}/{url_path}"

            auth_type = server.get("auth_type", "bearer")
            token = None

            if auth_type == "bearer":
                token = server.get("key", "")
            elif auth_type == "session":
                token = session_token
            server_entries.append((idx, server, full_url, token))

    # Create async tasks to fetch data
    tasks = [get_tool_server_data(token, url) for (_, _, url, token) in server_entries]

    # Execute tasks concurrently
    responses = await asyncio.gather(*tasks, return_exceptions=True)

    # Build final results with index and server metadata
    results = []
    for (idx, server, url, _), response in zip(server_entries, responses):
        if isinstance(response, Exception):
            print(f"Failed to connect to {url} OpenAPI tool server")
            continue

        results.append(
            {
                "idx": idx,
                "url": server.get("url"),
                "openapi": response.get("openapi"),
                "info": response.get("info"),
                "specs": response.get("specs"),
            }
        )

    return results


async def execute_tool_server(
    token: str, url: str, name: str, params: Dict[str, Any], server_data: Dict[str, Any]
) -> Any:
    error = None
    try:
        openapi = server_data.get("openapi", {})
        paths = openapi.get("paths", {})

        matching_route = None
        for route_path, methods in paths.items():
            for http_method, operation in methods.items():
                if isinstance(operation, dict) and operation.get("operationId") == name:
                    matching_route = (route_path, methods)
                    break
            if matching_route:
                break

        if not matching_route:
            raise Exception(f"No matching route found for operationId: {name}")

        route_path, methods = matching_route

        method_entry = None
        for http_method, operation in methods.items():
            if operation.get("operationId") == name:
                method_entry = (http_method.lower(), operation)
                break

        if not method_entry:
            raise Exception(f"No matching method found for operationId: {name}")

        http_method, operation = method_entry

        path_params = {}
        query_params = {}
        body_params = {}

        for param in operation.get("parameters", []):
            param_name = param["name"]
            param_in = param["in"]
            if param_name in params:
                if param_in == "path":
                    path_params[param_name] = params[param_name]
                elif param_in == "query":
                    query_params[param_name] = params[param_name]

        final_url = f"{url}{route_path}"
        for key, value in path_params.items():
            final_url = final_url.replace(f"{{{key}}}", str(value))

        if query_params:
            query_string = "&".join(f"{k}={v}" for k, v in query_params.items())
            final_url = f"{final_url}?{query_string}"

        if operation.get("requestBody", {}).get("content"):
            if params:
                body_params = params
            else:
                raise Exception(
                    f"Request body expected for operation '{name}' but none found."
                )

        headers = {"Content-Type": "application/json"}

        if token:
            headers["Authorization"] = f"Bearer {token}"

        async with aiohttp.ClientSession() as session:
            request_method = getattr(session, http_method.lower())

            if http_method in ["post", "put", "patch"]:
                async with request_method(
                    final_url, json=body_params, headers=headers
                ) as response:
                    if response.status >= 400:
                        text = await response.text()
                        raise Exception(f"HTTP error {response.status}: {text}")
                    return await response.json()
            else:
                async with request_method(final_url, headers=headers) as response:
                    if response.status >= 400:
                        text = await response.text()
                        raise Exception(f"HTTP error {response.status}: {text}")
                    return await response.json()

    except Exception as err:
        error = str(err)
        log.warning("Tool server request failed for operation %s", name)
        return {"error": error}
