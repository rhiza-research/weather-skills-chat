"""Langfuse tracing for weather-skills chats, LLM calls, and tool runs.

Uses the Langfuse Python SDK v4 (OpenTelemetry-based). Disabled unless both
LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are set (or LANGFUSE_ENABLED is
explicitly false). Failures never raise into the chat path.
"""

from __future__ import annotations

import contextvars
import copy
import json
import logging
import threading
from typing import Any, Callable, Optional

from starlette.responses import StreamingResponse

from open_webui.env import (
    LANGFUSE_ENABLED,
    LANGFUSE_HOST,
    LANGFUSE_PUBLIC_KEY,
    LANGFUSE_SECRET_KEY,
    LANGFUSE_TRACING_ENVIRONMENT,
)

log = logging.getLogger(__name__)

MAX_PAYLOAD_CHARS = 32_000
# Generations include full tool specs (skill descriptions); keep room to inspect.
MAX_GENERATION_INPUT_CHARS = 1_000_000

_client: Any = None
_client_failed = False
_client_lock = threading.Lock()
_trace_var: contextvars.ContextVar[Any] = contextvars.ContextVar(
    "langfuse_trace", default=None
)
_generation_stack_var: contextvars.ContextVar[list] = contextvars.ContextVar(
    "langfuse_generation_stack", default=None
)
_propagate_cm_var: contextvars.ContextVar[Any] = contextvars.ContextVar(
    "langfuse_propagate_cm", default=None
)
_trace_metadata_var: contextvars.ContextVar[Any] = contextvars.ContextVar(
    "langfuse_trace_metadata", default=None
)
_input_thread_var: contextvars.ContextVar[Any] = contextvars.ContextVar(
    "langfuse_input_thread", default=None
)
# A dict shared by every context copied after the trace starts. The first
# end_chat_trace in any of them marks it ended, so a later end in another
# copy (a tool loop task and the context that awaited it) does not end or
# update the root span again.
_trace_state_var: contextvars.ContextVar[Any] = contextvars.ContextVar(
    "langfuse_trace_state", default=None
)


def tracing_enabled() -> bool:
    return bool(LANGFUSE_ENABLED and LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY)


def get_client():
    global _client, _client_failed
    if not tracing_enabled() or _client_failed:
        return None
    if _client is not None:
        return _client
    with _client_lock:
        if _client is not None or _client_failed:
            return _client
        try:
            from langfuse import Langfuse

            _client = Langfuse(
                public_key=LANGFUSE_PUBLIC_KEY,
                secret_key=LANGFUSE_SECRET_KEY,
                base_url=LANGFUSE_HOST,
                # Required for Langfuse Cloud v4 realtime processing of OTLP spans.
                # Without this, the UI can lag by minutes even after flush().
                additional_headers={"x-langfuse-ingestion-version": "4"},
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


def _create_chat_trace(
    *,
    user: Any,
    metadata: Optional[dict],
    form_data: Optional[dict],
    source: str = "chat",
) -> tuple[Any, Any, Optional[dict]]:
    client = get_client()
    if not client:
        return None, None, None
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
    # The SDK copies propagated attributes onto a span when the span starts,
    # so the context must be entered before the root span is created.
    if cm is not None:
        try:
            cm.__enter__()
        except Exception:
            log.debug("Langfuse propagate_attributes enter failed", exc_info=True)
            cm = None
    try:
        trace = _safe_call(
            client.start_observation,
            name="weather-skills-chat",
            as_type="span",
            input=trace_input,
            metadata=trace_metadata,
        )
        if trace is None:
            _exit_entered_propagation(cm)
            return None, None, None
        return trace, cm, trace_metadata
    except Exception:
        _exit_entered_propagation(cm)
        raise


def _exit_entered_propagation(cm: Any) -> None:
    """Exit a cm the caller holds, before it is stored in _propagate_cm_var.

    _exit_propagate_attributes exits the stored cm and clears the slot.
    """
    if cm is None:
        return
    try:
        cm.__exit__(None, None, None)
    except Exception:
        log.debug("Langfuse propagate_attributes exit failed", exc_info=True)


def _activate_chat_trace(trace: Any, cm: Any, trace_metadata: Optional[dict]) -> None:
    """Track a trace from _create_chat_trace, whose cm is already entered."""
    if cm is not None:
        _propagate_cm_var.set(cm)
    if trace is not None:
        _trace_var.set(trace)
        _trace_metadata_var.set(trace_metadata)
        _trace_state_var.set({"ended": False})


def start_chat_trace(
    *,
    user: Any,
    metadata: Optional[dict],
    form_data: Optional[dict],
    source: str = "chat",
) -> Any:
    trace, cm, trace_metadata = _create_chat_trace(
        user=user, metadata=metadata, form_data=form_data, source=source
    )
    _activate_chat_trace(trace, cm, trace_metadata)
    return trace


def begin_chat_trace(
    *,
    user: Any,
    metadata: Optional[dict],
    form_data: Optional[dict],
    source: str = "chat",
) -> Any:
    """Create the root span now so its ids exist before the first model call.

    The span starts with only the model as input. Provider-traced model calls
    need the span's trace id and id when the request body is built. A
    background thread truncates the message list and attaches it with
    ``span.update(input=...)``, off the send path.

    Never raises: on any failure the chat runs without a trace.
    """
    trace = None
    cm = None
    try:
        if not tracing_enabled():
            return None
        model = (form_data or {}).get("model")
        messages = copy.deepcopy((form_data or {}).get("messages") or [])
        trace, cm, trace_metadata = _create_chat_trace(
            user=user,
            metadata=copy.copy(metadata or {}),
            form_data={"model": model},
            source=source,
        )
        if trace is None:
            return None

        def _attach_input():
            _safe_call(
                trace.update,
                input=truncate_payload({"model": model, "messages": messages}),
            )

        thread = threading.Thread(
            target=_attach_input, name="langfuse-chat-trace-input", daemon=True
        )
    except Exception:
        log.debug("Langfuse begin_chat_trace failed", exc_info=True)
        if trace is not None:
            _safe_call(trace.end)
        _exit_entered_propagation(cm)
        return None
    _activate_chat_trace(trace, cm, trace_metadata)
    try:
        thread.start()
        _input_thread_var.set(thread)
    except Exception:
        log.debug("Langfuse chat trace input thread failed to start", exc_info=True)
    return trace


def _clear_trace_context() -> None:
    _trace_var.set(None)
    _trace_metadata_var.set(None)
    _trace_state_var.set(None)
    _input_thread_var.set(None)
    _generation_stack_var.set(None)


def chat_trace_ended() -> bool:
    """Whether some context copy has already ended this context's root span."""
    state = _trace_state_var.get()
    return bool(state and state.get("ended"))


def end_chat_trace(*, output: Any = None, error: Any = None) -> None:
    state = _trace_state_var.get()
    if state is not None and state.get("ended"):
        # Another context copy already ended the root span and exited the
        # propagation cm. Exiting it again here would detach it in a context
        # that did not enter it, so only the slot is cleared.
        _clear_trace_context()
        _propagate_cm_var.set(None)
        return
    if state is not None:
        state["ended"] = True
    # An ended span drops updates, so the input must land first.
    input_thread = _input_thread_var.get()
    if input_thread is not None:
        input_thread.join(timeout=5.0)
        if input_thread.is_alive():
            log.debug("Langfuse chat trace input was not attached before end")
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
        _clear_trace_context()
        _exit_propagate_attributes()
        client = get_client()
        if client:
            _safe_call(client.flush)


# Who records a connection's model calls, set per connection as
# ``model_call_tracing`` in OPENAI_API_CONFIGS. "app" records a generation
# here. A provider style sends that provider's trace-linking fields in the
# request body and the provider records the call with the real model and cost.
MODEL_CALL_TRACING_KEY = "model_call_tracing"
MODEL_CALL_TRACING_APP = "app"
MODEL_CALL_TRACING_OPENROUTER = "openrouter"

_warned_tracing_styles: set = set()
_warned_tracing_styles_lock = threading.Lock()


def _openrouter_trace_fields(
    *,
    trace: Any,
    trace_metadata: Optional[dict],
    user: Any,
    metadata: Optional[dict],
) -> dict:
    """OpenRouter Broadcast fields: ``user``, ``session_id``, ``trace``."""
    fields: dict[str, Any] = {}
    user_id = _trace_user_id(user)
    if user_id:
        fields["user"] = user_id
    source = trace_metadata if trace is not None and trace_metadata else metadata
    source = source if isinstance(source, dict) else {}
    chat_id = source.get("chat_id")
    if chat_id:
        fields["session_id"] = str(chat_id)[:256]
    if trace is None:
        return fields
    trace_id = getattr(trace, "trace_id", None)
    parent_span_id = getattr(trace, "id", None)
    trace_fields = {
        # Both ids or neither; half a pair cannot nest the call.
        "trace_id": trace_id if trace_id and parent_span_id else None,
        "parent_span_id": parent_span_id if trace_id and parent_span_id else None,
        "environment": LANGFUSE_TRACING_ENVIRONMENT,
        "generation_name": "llm",
        "chat_id": source.get("chat_id"),
        "message_id": source.get("message_id"),
        "model": source.get("model"),
        "tool_ids": source.get("tool_ids"),
    }
    fields["trace"] = {k: v for k, v in trace_fields.items() if v is not None}
    return fields


# Style -> builder of the request-body fields that let that provider record
# the call inside the app's trace. To add a provider (for example LiteLLM),
# write a builder with the same keyword arguments as _openrouter_trace_fields
# and register its style here. The connection modal's style select lists the
# styles an admin can pick.
_PROVIDER_TRACE_FIELD_BUILDERS: dict[str, Callable[..., dict]] = {
    MODEL_CALL_TRACING_OPENROUTER: _openrouter_trace_fields,
}


def model_call_tracing_style(
    config: Optional[dict], *, warn_unknown: bool = True
) -> str:
    """The style in a connection config or call metadata; unset or unknown is "app".

    Pass ``warn_unknown=False`` for call metadata, whose values come from
    clients and must not grow the warned set or the log.
    """
    style = str((config or {}).get(MODEL_CALL_TRACING_KEY) or MODEL_CALL_TRACING_APP)
    if style == MODEL_CALL_TRACING_APP or style in _PROVIDER_TRACE_FIELD_BUILDERS:
        return style
    if warn_unknown:
        with _warned_tracing_styles_lock:
            first = style not in _warned_tracing_styles
            _warned_tracing_styles.add(style)
        if first:
            log.warning(
                "Unknown %s %r; the app records these model calls",
                MODEL_CALL_TRACING_KEY,
                style,
            )
    return MODEL_CALL_TRACING_APP


def apply_provider_trace_fields(
    payload: dict,
    style: str,
    *,
    user: Any,
    metadata: Optional[dict],
) -> dict:
    """Add the style's provider fields to an outgoing request body.

    Mutates ``payload`` in place and returns the same dict. The body is
    unchanged for "app" and when Langfuse tracing is off.
    """
    builder = _PROVIDER_TRACE_FIELD_BUILDERS.get(style)
    if builder is None or not tracing_enabled():
        return payload
    try:
        fields = builder(
            trace=current_trace(),
            trace_metadata=_trace_metadata_var.get(),
            user=user,
            metadata=metadata,
        )
    except Exception:
        log.debug("Building %s trace fields failed", style, exc_info=True)
        return payload
    payload.update(fields)
    return payload


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
    tools = form_data.get("tools") or []
    tool_names = []
    for tool in tools:
        name = (tool.get("function") or {}).get("name")
        if name:
            tool_names.append(name)
    # Include full tool specs (names + descriptions + parameters) so Langfuse
    # shows what the model actually received — not just tool name metadata.
    generation_input: dict[str, Any] = {
        "messages": form_data.get("messages"),
    }
    if tools:
        generation_input["tools"] = tools
    metadata: dict[str, Any] = {}
    if tool_names:
        metadata["tool_names"] = tool_names
        metadata["tool_count"] = len(tool_names)
    generation = _safe_call(
        trace.start_observation,
        name="llm",
        as_type="generation",
        model=form_data.get("model"),
        input=truncate_payload(
            generation_input, limit=MAX_GENERATION_INPUT_CHARS
        ),
        model_parameters=model_parameters or None,
        metadata=metadata or None,
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
    details = usage.get("prompt_tokens_details") or usage.get("input_tokens_details")
    if isinstance(details, dict):
        cached = details.get("cached_tokens")
        cache_write = details.get("cache_write_tokens")
        if cached is not None:
            mapped["cache_read_input_tokens"] = cached
        if cache_write is not None:
            mapped["cache_creation_input_tokens"] = cache_write
    # Native Anthropic-style fields (if a provider surfaces them directly)
    for src, dst in (
        ("cache_read_input_tokens", "cache_read_input_tokens"),
        ("cache_creation_input_tokens", "cache_creation_input_tokens"),
    ):
        if usage.get(src) is not None and dst not in mapped:
            mapped[dst] = usage.get(src)
    if all(
        v is None
        for k, v in mapped.items()
        if k in ("input", "output", "total")
    ):
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
    # Push mid-turn generations promptly (tool loops can run a long time).
    client = get_client()
    if client:
        _safe_call(client.flush)


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


def _error_text(error: Any) -> str:
    status_code = getattr(error, "status_code", None)
    detail = getattr(error, "detail", None)
    if status_code is not None and detail is not None:
        return f"HTTP {status_code}: {detail}"
    return str(error) or type(error).__name__


def _provider_response_failure(response: Any) -> Optional[str]:
    """Why a provider-traced call failed on the app side, else None."""
    status_code = getattr(response, "status_code", None)
    if isinstance(status_code, int) and status_code >= 400:
        return f"HTTP {status_code}"
    if isinstance(response, dict) and response.get("error"):
        return str(response.get("error"))
    return None


def record_provider_call_error(style: str, error: str) -> None:
    """Record a failed provider-traced call as an ERROR span under the root.

    The provider may never see or record a call that fails here, so without
    this span the failure would not appear in Langfuse. It is a span, not a
    generation, so it carries no usage or cost.
    """
    trace = current_trace()
    if not trace:
        return
    span = _safe_call(
        trace.start_observation,
        name="llm",
        as_type="span",
        level="ERROR",
        status_message=error,
        metadata={MODEL_CALL_TRACING_KEY: style},
    )
    if span is not None:
        _safe_call(span.end)


async def observe_generation(
    form_data: dict, coro, *, style: str = MODEL_CALL_TRACING_APP
):
    """Record the model call as a generation unless its provider records it.

    Callers resolve the style first, so a provider-traced call never creates
    a generation here.
    """
    if style != MODEL_CALL_TRACING_APP:
        try:
            response = await coro
        except Exception as e:
            record_provider_call_error(style, _error_text(e))
            raise
        failure = _provider_response_failure(response)
        if failure is not None:
            record_provider_call_error(style, failure)
        return response
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
