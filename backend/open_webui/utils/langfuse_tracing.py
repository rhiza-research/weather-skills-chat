"""Langfuse tracing for weather-skills chats, LLM calls, and tool runs.

Uses the Langfuse Python SDK v4 (OpenTelemetry-based). Disabled unless both
LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are set (or LANGFUSE_ENABLED is
explicitly false). Failures never raise into the chat path.
"""

from __future__ import annotations

import contextvars
import json
import logging
from typing import Any, Callable, Optional

from starlette.responses import StreamingResponse

from open_webui.env import (
    LANGFUSE_ENABLED,
    LANGFUSE_HOST,
    LANGFUSE_PUBLIC_KEY,
    LANGFUSE_SECRET_KEY,
)

log = logging.getLogger(__name__)

MAX_PAYLOAD_CHARS = 32_000

_client: Any = None
_client_failed = False
_trace_var: contextvars.ContextVar[Any] = contextvars.ContextVar(
    "langfuse_trace", default=None
)
_generation_stack_var: contextvars.ContextVar[list] = contextvars.ContextVar(
    "langfuse_generation_stack", default=None
)
_propagate_cm_var: contextvars.ContextVar[Any] = contextvars.ContextVar(
    "langfuse_propagate_cm", default=None
)


def tracing_enabled() -> bool:
    return bool(LANGFUSE_ENABLED and LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY)


def get_client():
    global _client, _client_failed
    if not tracing_enabled() or _client_failed:
        return None
    if _client is None:
        try:
            from langfuse import Langfuse

            _client = Langfuse(
                public_key=LANGFUSE_PUBLIC_KEY,
                secret_key=LANGFUSE_SECRET_KEY,
                base_url=LANGFUSE_HOST,
            )
            log.info("Langfuse tracing enabled (host=%s)", LANGFUSE_HOST)
        except Exception:
            _client_failed = True
            log.exception("Failed to initialize Langfuse client; tracing disabled")
            return None
    return _client


def shutdown_langfuse() -> None:
    _exit_propagate_attributes()
    client = _client
    if not client:
        return
    try:
        client.flush()
        shutdown = getattr(client, "shutdown", None)
        if callable(shutdown):
            shutdown()
    except Exception:
        log.debug("Langfuse shutdown failed", exc_info=True)


def truncate_payload(obj: Any, limit: int = MAX_PAYLOAD_CHARS) -> Any:
    try:
        encoded = json.dumps(obj, default=str)
    except Exception:
        encoded = str(obj)
    if len(encoded) <= limit:
        try:
            return json.loads(encoded)
        except Exception:
            return encoded
    return encoded[:limit] + f"...[truncated {len(encoded) - limit} chars]"


def _safe_call(fn: Callable, *args, **kwargs) -> Any:
    try:
        return fn(*args, **kwargs)
    except Exception:
        log.debug(
            "Langfuse call failed: %s", getattr(fn, "__name__", fn), exc_info=True
        )
        return None


def _exit_propagate_attributes() -> None:
    cm = _propagate_cm_var.get()
    if cm is None:
        return
    try:
        cm.__exit__(None, None, None)
    except Exception:
        log.debug("Langfuse propagate_attributes exit failed", exc_info=True)
    finally:
        _propagate_cm_var.set(None)


def current_trace():
    return _trace_var.get()


def _trace_user_id(user: Any) -> Optional[str]:
    email = getattr(user, "email", None)
    if email:
        return str(email)
    user_id = getattr(user, "id", None)
    return str(user_id) if user_id is not None else None


def start_chat_trace(
    *,
    user: Any,
    metadata: Optional[dict],
    form_data: Optional[dict],
    source: str = "chat",
) -> Any:
    client = get_client()
    if not client:
        return None
    metadata = metadata or {}
    form_data = form_data or {}
    if metadata.get("headless"):
        source = "automation"
    tags = ["weather-skills", source]
    chat_id = metadata.get("chat_id")
    model = form_data.get("model")
    if not model:
        meta_model = metadata.get("model") or {}
        model = meta_model.get("id") if isinstance(meta_model, dict) else None

    trace_input = truncate_payload(
        {
            "model": form_data.get("model"),
            "messages": form_data.get("messages"),
        }
    )
    trace_metadata = {
        "chat_id": chat_id,
        "message_id": metadata.get("message_id"),
        "model": model,
        "tool_ids": metadata.get("tool_ids"),
        "user_id": getattr(user, "id", None),
        "source": source,
        "function_calling": metadata.get("function_calling"),
    }

    from langfuse import propagate_attributes

    cm = propagate_attributes(
        user_id=_trace_user_id(user),
        session_id=chat_id,
        tags=tags,
        metadata=trace_metadata,
    )
    _safe_call(cm.__enter__)
    _propagate_cm_var.set(cm)

    trace = _safe_call(
        client.start_observation,
        name="weather-skills-chat",
        as_type="span",
        input=trace_input,
        metadata=trace_metadata,
    )
    if trace is not None:
        _trace_var.set(trace)
    else:
        _exit_propagate_attributes()
    return trace


def end_chat_trace(*, output: Any = None, error: Any = None) -> None:
    while _generation_stack():
        end_generation(error=error or "trace closed")
    trace = _trace_var.get()
    try:
        if trace:
            if error is not None:
                _safe_call(
                    trace.update,
                    output=truncate_payload(str(error)),
                    level="ERROR",
                    status_message=str(error),
                )
            elif output is not None:
                _safe_call(trace.update, output=truncate_payload(output))
            _safe_call(trace.end)
    except Exception:
        log.debug("Langfuse end_chat_trace failed", exc_info=True)
    finally:
        _trace_var.set(None)
        _generation_stack_var.set(None)
        _exit_propagate_attributes()
        client = get_client()
        if client:
            _safe_call(client.flush)


def _generation_stack() -> list:
    stack = _generation_stack_var.get()
    if stack is None:
        stack = []
        _generation_stack_var.set(stack)
    return stack


def start_generation(form_data: Optional[dict]) -> Any:
    trace = current_trace()
    if not trace:
        return None
    form_data = form_data or {}
    model_parameters = {}
    for key in (
        "temperature",
        "max_tokens",
        "max_completion_tokens",
        "top_p",
        "frequency_penalty",
        "presence_penalty",
        "seed",
        "reasoning_effort",
    ):
        if form_data.get(key) is not None:
            model_parameters[key] = form_data[key]
    tool_names = []
    for tool in form_data.get("tools") or []:
        name = (tool.get("function") or {}).get("name")
        if name:
            tool_names.append(name)
    generation = _safe_call(
        trace.start_observation,
        name="llm",
        as_type="generation",
        model=form_data.get("model"),
        input=truncate_payload(form_data.get("messages")),
        model_parameters=model_parameters or None,
        metadata={"tools": tool_names} if tool_names else None,
    )
    if generation is not None:
        _generation_stack().append(generation)
    return generation


def map_usage(usage: Any) -> Optional[dict]:
    if not isinstance(usage, dict):
        return None
    mapped = {
        "input": usage.get("prompt_tokens", usage.get("input")),
        "output": usage.get("completion_tokens", usage.get("output")),
        "total": usage.get("total_tokens", usage.get("total")),
    }
    if all(v is None for v in mapped.values()):
        return None
    return {k: v for k, v in mapped.items() if v is not None}


def end_generation(*, output: Any = None, usage: Any = None, error: Any = None) -> None:
    stack = _generation_stack()
    if not stack:
        return
    generation = stack.pop()
    update_kwargs: dict[str, Any] = {}
    if error is not None:
        update_kwargs["level"] = "ERROR"
        update_kwargs["status_message"] = str(error)
        update_kwargs["output"] = truncate_payload(str(error))
    elif output is not None:
        update_kwargs["output"] = truncate_payload(output)
    mapped = map_usage(usage)
    if mapped:
        update_kwargs["usage_details"] = mapped
    if update_kwargs:
        _safe_call(generation.update, **update_kwargs)
    _safe_call(generation.end)


def start_tool_observation(name: str, params: Any) -> Any:
    trace = current_trace()
    if not trace:
        return None
    return _safe_call(
        trace.start_observation,
        name=f"tool:{name or 'unknown'}",
        as_type="tool",
        input=truncate_payload(params),
        metadata={"tool": name},
    )


def end_tool_observation(span: Any, *, output: Any = None, error: Any = None) -> None:
    if not span:
        return
    update_kwargs: dict[str, Any] = {}
    if error is not None:
        update_kwargs["level"] = "ERROR"
        update_kwargs["status_message"] = str(error)
        update_kwargs["output"] = truncate_payload(str(error))
    elif output is not None:
        update_kwargs["output"] = truncate_payload(output)
    if update_kwargs:
        _safe_call(span.update, **update_kwargs)
    _safe_call(span.end)


def message_from_completion(response: Any) -> Any:
    if not isinstance(response, dict):
        return response
    choices = response.get("choices") or []
    if not choices:
        if response.get("error"):
            return {"error": response.get("error")}
        return response
    message = (choices[0] or {}).get("message") or {}
    output: dict[str, Any] = {}
    if message.get("content") is not None:
        output["content"] = message.get("content")
    if message.get("tool_calls"):
        output["tool_calls"] = message.get("tool_calls")
    if message.get("reasoning_content"):
        output["reasoning_content"] = message.get("reasoning_content")
    return output or message or response


def usage_from_completion(response: Any) -> Any:
    if isinstance(response, dict):
        return response.get("usage")
    return None


def new_sse_state() -> dict:
    return {
        "buf": "",
        "content": [],
        "tool_calls": {},
        "usage": None,
        "error": None,
        "selected_model_id": None,
    }


def ingest_sse_chunk(state: dict, chunk: Any) -> None:
    if chunk is None:
        return
    if isinstance(chunk, bytes):
        text = chunk.decode("utf-8", errors="replace")
    else:
        text = str(chunk)
    state["buf"] += text
    while "\n" in state["buf"]:
        line, state["buf"] = state["buf"].split("\n", 1)
        _ingest_sse_line(state, line)


def _ingest_sse_line(state: dict, line: str) -> None:
    line = line.strip()
    if not line.startswith("data:"):
        return
    data = line[5:].strip()
    if not data or data == "[DONE]":
        return
    try:
        obj = json.loads(data)
    except json.JSONDecodeError:
        return
    if not isinstance(obj, dict):
        return
    if obj.get("usage"):
        state["usage"] = obj["usage"]
    if obj.get("error"):
        state["error"] = obj["error"]
    if obj.get("selected_model_id"):
        state["selected_model_id"] = obj["selected_model_id"]
    for choice in obj.get("choices") or []:
        if not isinstance(choice, dict):
            continue
        delta = choice.get("delta") or {}
        message = choice.get("message") or {}
        content = delta.get("content")
        if content is None:
            content = message.get("content")
        if content:
            state["content"].append(content)
        tool_calls = delta.get("tool_calls") or message.get("tool_calls") or []
        for tool_call in tool_calls:
            if not isinstance(tool_call, dict):
                continue
            idx = tool_call.get("index", len(state["tool_calls"]))
            acc = state["tool_calls"].setdefault(
                idx,
                {
                    "id": "",
                    "type": "function",
                    "function": {"name": "", "arguments": ""},
                },
            )
            if tool_call.get("id"):
                acc["id"] = tool_call["id"]
            if tool_call.get("type"):
                acc["type"] = tool_call["type"]
            fn = tool_call.get("function") or {}
            if fn.get("name"):
                acc["function"]["name"] += fn["name"]
            if fn.get("arguments"):
                acc["function"]["arguments"] += fn["arguments"]


def output_from_sse_state(state: dict) -> dict:
    ingest_sse_chunk(state, "\n")
    output: dict[str, Any] = {}
    if state["content"]:
        output["content"] = "".join(state["content"])
    if state["tool_calls"]:
        output["tool_calls"] = [
            state["tool_calls"][k] for k in sorted(state["tool_calls"])
        ]
    if state["error"]:
        output["error"] = state["error"]
    if state["selected_model_id"]:
        output["selected_model_id"] = state["selected_model_id"]
    return output


def bind_generation_to_response(response: Any) -> Any:
    if not _generation_stack():
        return response
    if isinstance(response, StreamingResponse):
        return StreamingResponse(
            _tee_generation_stream(response.body_iterator),
            status_code=getattr(response, "status_code", 200),
            headers=dict(response.headers) if response.headers else None,
            media_type=response.media_type,
            background=response.background,
        )
    end_generation(
        output=message_from_completion(response),
        usage=usage_from_completion(response),
        error=(response.get("error") if isinstance(response, dict) else None),
    )
    return response


async def _tee_generation_stream(iterator):
    state = new_sse_state()
    try:
        if hasattr(iterator, "__aiter__"):
            async for chunk in iterator:
                ingest_sse_chunk(state, chunk)
                yield chunk
        else:
            for chunk in iterator:
                ingest_sse_chunk(state, chunk)
                yield chunk
        output = output_from_sse_state(state)
        end_generation(
            output=output,
            usage=state.get("usage"),
            error=state.get("error"),
        )
    except Exception as e:
        end_generation(error=e)
        raise


async def observe_generation(form_data: dict, coro):
    start_generation(form_data)
    try:
        response = await coro
        return bind_generation_to_response(response)
    except Exception as e:
        end_generation(error=e)
        raise


async def observe_stream_and_end_trace(iterator, *, output: Any = None):
    """Yield a fallback HTTP stream, then close the chat trace."""
    error = None
    try:
        if hasattr(iterator, "__aiter__"):
            async for chunk in iterator:
                yield chunk
        else:
            for chunk in iterator:
                yield chunk
    except Exception as e:
        error = e
        raise
    finally:
        end_chat_trace(output=output, error=error)
