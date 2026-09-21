import logging
from typing import Any, Optional

from fastapi import HTTPException, Request, status
from starlette.responses import StreamingResponse

from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.organizations import Organizations
from open_webui.models.usage import (
    ORG_LIMIT_MESSAGE,
    USER_LIMIT_MESSAGE,
    Usage,
    UsageLimitExceeded,
    UsageMeModel,
    current_period,
    empty_totals,
)
from open_webui.utils.langfuse_tracing import ingest_sse_chunk, new_sse_state

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MAIN"])


def inject_include_usage(form_data: dict) -> dict:
    if form_data.get("stream"):
        opts = form_data.get("stream_options")
        if not isinstance(opts, dict):
            opts = {}
        opts["include_usage"] = True
        form_data["stream_options"] = opts
    return form_data


def resolve_usage_context(request: Request, form_data: dict, user) -> dict:
    state_meta = getattr(request.state, "metadata", None)
    state_meta = state_meta if isinstance(state_meta, dict) else {}
    form_meta = form_data.get("metadata") if isinstance(form_data.get("metadata"), dict) else {}
    org_id = (
        state_meta.get("organization_id")
        or form_meta.get("organization_id")
        or (request.headers.get("X-Organization-Id") or "").strip()
        or getattr(user, "id", None)
    )
    source = form_meta.get("usage_source") or state_meta.get("usage_source")
    if not source:
        if form_meta.get("task") or state_meta.get("task"):
            source = "task"
        elif form_meta.get("headless") or state_meta.get("headless"):
            source = "automation"
        else:
            source = "chat"
    model_id = form_data.get("model")
    if not model_id:
        model = state_meta.get("model") or form_meta.get("model") or {}
        model_id = model.get("id") if isinstance(model, dict) else None
    return {
        "organization_id": org_id,
        "user_id": getattr(user, "id", None),
        "source": source,
        "model_id": model_id,
        "chat_id": form_meta.get("chat_id") or state_meta.get("chat_id"),
        "message_id": form_meta.get("message_id") or state_meta.get("message_id"),
    }


def remaining_usd(limit: Optional[float], used: float) -> Optional[float]:
    if limit is None:
        return None
    return max(0.0, float(limit) - float(used or 0.0))


def check_usage_caps(organization_id: str, user_id: str) -> None:
    if not organization_id or not user_id:
        return
    org = Organizations.get_organization_by_id(organization_id)
    if not org:
        return
    period = current_period()
    if org.monthly_limit_usd is not None:
        org_used = Usage.get_month(organization_id, "", period).cost_usd
        if org_used >= org.monthly_limit_usd:
            raise UsageLimitExceeded(ORG_LIMIT_MESSAGE)
    member = Organizations.get_member(organization_id, user_id)
    user_limit = member.monthly_limit_usd if member else None
    if user_limit is not None:
        user_used = Usage.get_month(organization_id, user_id, period).cost_usd
        if user_used >= user_limit:
            raise UsageLimitExceeded(USER_LIMIT_MESSAGE)


def enforce_usage_caps(request: Request, form_data: dict, user) -> None:
    ctx = resolve_usage_context(request, form_data, user)
    try:
        check_usage_caps(ctx["organization_id"], ctx["user_id"])
    except UsageLimitExceeded as e:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=e.detail
        ) from e


def record_provider_usage(usage: Optional[dict], context: dict) -> None:
    try:
        Usage.record_event(
            organization_id=context.get("organization_id"),
            user_id=context.get("user_id"),
            usage=usage,
            model_id=context.get("model_id"),
            source=context.get("source") or "chat",
            chat_id=context.get("chat_id"),
            message_id=context.get("message_id"),
        )
    except Exception:
        log.exception("Failed to record usage event")


def bind_usage_to_response(response: Any, context: dict) -> Any:
    if isinstance(response, dict):
        record_provider_usage(response.get("usage"), context)
        return response
    if isinstance(response, StreamingResponse):
        return StreamingResponse(
            _record_usage_stream(response.body_iterator, context),
            status_code=getattr(response, "status_code", 200),
            headers=dict(response.headers) if response.headers else None,
            media_type=response.media_type,
            background=response.background,
        )
    return response


async def _record_usage_stream(iterator, context: dict):
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
        if state.get("usage"):
            record_provider_usage(state.get("usage"), context)
    except Exception:
        raise


def usage_snapshot(organization_id: str, user_id: str) -> UsageMeModel:
    period = current_period()
    org = Organizations.get_organization_by_id(organization_id)
    member = Organizations.get_member(organization_id, user_id)
    user_row = Usage.get_month(organization_id, user_id, period)
    org_row = Usage.get_month(organization_id, "", period)
    org_limit = org.monthly_limit_usd if org else None
    user_limit = member.monthly_limit_usd if member else None
    org_remaining = remaining_usd(org_limit, org_row.cost_usd)
    user_remaining = remaining_usd(user_limit, user_row.cost_usd)

    remaining = None
    if org_remaining is not None and user_remaining is not None:
        remaining = min(org_remaining, user_remaining)
    elif org_remaining is not None:
        remaining = org_remaining
    elif user_remaining is not None:
        remaining = user_remaining

    if user_limit is not None:
        effective = user_limit
    else:
        effective = org_limit

    message = None
    over = False
    if org_limit is not None and org_row.cost_usd >= org_limit:
        over = True
        message = ORG_LIMIT_MESSAGE
    elif user_limit is not None and user_row.cost_usd >= user_limit:
        over = True
        message = USER_LIMIT_MESSAGE

    return UsageMeModel(
        organization_id=organization_id,
        organization_name=org.name if org else "",
        period=period,
        cost_usd=user_row.cost_usd,
        org_cost_usd=org_row.cost_usd,
        prompt_tokens=user_row.prompt_tokens,
        completion_tokens=user_row.completion_tokens,
        total_tokens=user_row.total_tokens,
        cached_tokens=user_row.cached_tokens,
        uncached_tokens=user_row.uncached_tokens,
        org_limit_usd=org_limit,
        user_limit_usd=user_limit,
        effective_limit_usd=effective,
        remaining_usd=remaining,
        over_limit=over,
        message=message,
    )


def attach_org_usage(org, *, include_members: bool = False):
    period = current_period()
    org.usage = Usage.get_month(org.id, "", period)
    if include_members and org.members:
        by_user = Usage.get_user_months(
            org.id, [m.user_id for m in org.members], period
        )
        for member in org.members:
            member.usage = by_user.get(member.user_id) or empty_totals(
                org.id, member.user_id, period
            )
    return org


def attach_org_usage_list(orgs: list) -> list:
    period = current_period()
    totals = Usage.get_org_totals([org.id for org in orgs], period)
    for org in orgs:
        org.usage = totals.get(org.id) or empty_totals(org.id, "", period)
    return orgs
