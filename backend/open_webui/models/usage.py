import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

from open_webui.env import SRC_LOG_LEVELS
from open_webui.internal.db import Base, JSONField, get_db
from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, Column, Float, Integer, Text

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

ORG_TOTAL_USER_ID = ""
DEFAULT_ORG_MONTHLY_LIMIT_USD = 300.0

ORG_LIMIT_MESSAGE = "This workspace has reached its monthly usage limit."
USER_LIMIT_MESSAGE = "You have reached your monthly usage limit in this workspace."


class UsageLimitExceeded(Exception):
    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


class UsageEvent(Base):
    __tablename__ = "usage_event"

    id = Column(Text, unique=True, primary_key=True)
    created_at = Column(BigInteger, nullable=False)
    organization_id = Column(Text, nullable=False)
    user_id = Column(Text, nullable=False)
    chat_id = Column(Text, nullable=True)
    message_id = Column(Text, nullable=True)
    model_id = Column(Text, nullable=True)
    source = Column(Text, nullable=False)
    prompt_tokens = Column(Integer, nullable=False, default=0)
    completion_tokens = Column(Integer, nullable=False, default=0)
    total_tokens = Column(Integer, nullable=False, default=0)
    cached_tokens = Column(Integer, nullable=False, default=0)
    uncached_tokens = Column(Integer, nullable=False, default=0)
    cost_usd = Column(Float, nullable=False, default=0.0)
    period = Column(Text, nullable=False)
    raw = Column(JSONField, nullable=True)


class UsageMonth(Base):
    __tablename__ = "usage_month"

    organization_id = Column(Text, primary_key=True)
    user_id = Column(Text, primary_key=True)
    period = Column(Text, primary_key=True)
    prompt_tokens = Column(Integer, nullable=False, default=0)
    completion_tokens = Column(Integer, nullable=False, default=0)
    total_tokens = Column(Integer, nullable=False, default=0)
    cached_tokens = Column(Integer, nullable=False, default=0)
    uncached_tokens = Column(Integer, nullable=False, default=0)
    cost_usd = Column(Float, nullable=False, default=0.0)


class UsageTotalsModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    organization_id: str = ""
    user_id: str = ""
    period: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cached_tokens: int = 0
    uncached_tokens: int = 0
    cost_usd: float = 0.0


class UsageMeModel(BaseModel):
    organization_id: str
    organization_name: str = ""
    period: str
    cost_usd: float = 0.0
    org_cost_usd: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cached_tokens: int = 0
    uncached_tokens: int = 0
    org_limit_usd: Optional[float] = None
    user_limit_usd: Optional[float] = None
    effective_limit_usd: Optional[float] = None
    remaining_usd: Optional[float] = None
    over_limit: bool = False
    message: Optional[str] = None


def current_period(now: Optional[datetime] = None) -> str:
    dt = now or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m")


def _as_int(value, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def _as_float(value) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_provider_usage(usage: Optional[dict]) -> dict:
    """Extract token counts and provider cost. Never estimates cost."""
    usage = usage if isinstance(usage, dict) else {}
    prompt = _as_int(
        usage.get("prompt_tokens", usage.get("input_tokens", usage.get("promptTokens")))
    )
    completion = _as_int(
        usage.get(
            "completion_tokens",
            usage.get("output_tokens", usage.get("completionTokens")),
        )
    )
    total = _as_int(usage.get("total_tokens", usage.get("totalTokens")), prompt + completion)
    details = usage.get("prompt_tokens_details") or usage.get("input_tokens_details") or {}
    if not isinstance(details, dict):
        details = {}
    cached = _as_int(details.get("cached_tokens", details.get("cachedTokens")))
    uncached = max(0, prompt - cached)

    cost = _as_float(usage.get("cost"))
    has_cost = cost is not None
    if not has_cost:
        cost_details = usage.get("cost_details") or usage.get("costDetails") or {}
        if isinstance(cost_details, dict):
            cost = _as_float(cost_details.get("upstream_inference_cost"))
            has_cost = cost is not None
    if cost is None:
        cost = 0.0

    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
        "cached_tokens": cached,
        "uncached_tokens": uncached,
        "cost_usd": float(cost),
        "has_cost": has_cost,
    }


def empty_totals(
    organization_id: str = "", user_id: str = "", period: Optional[str] = None
) -> UsageTotalsModel:
    return UsageTotalsModel(
        organization_id=organization_id,
        user_id=user_id,
        period=period or current_period(),
    )


class UsageTable:
    def get_month(
        self, organization_id: str, user_id: str, period: Optional[str] = None
    ) -> UsageTotalsModel:
        period = period or current_period()
        with get_db() as db:
            row = (
                db.query(UsageMonth)
                .filter_by(
                    organization_id=organization_id, user_id=user_id, period=period
                )
                .first()
            )
            if not row:
                return empty_totals(organization_id, user_id, period)
            return UsageTotalsModel.model_validate(row)

    def get_org_totals(
        self, organization_ids: list[str], period: Optional[str] = None
    ) -> dict[str, UsageTotalsModel]:
        period = period or current_period()
        if not organization_ids:
            return {}
        with get_db() as db:
            rows = (
                db.query(UsageMonth)
                .filter(
                    UsageMonth.organization_id.in_(organization_ids),
                    UsageMonth.user_id == ORG_TOTAL_USER_ID,
                    UsageMonth.period == period,
                )
                .all()
            )
            return {
                row.organization_id: UsageTotalsModel.model_validate(row)
                for row in rows
            }

    def get_user_months(
        self,
        organization_id: str,
        user_ids: list[str],
        period: Optional[str] = None,
    ) -> dict[str, UsageTotalsModel]:
        period = period or current_period()
        if not user_ids:
            return {}
        with get_db() as db:
            rows = (
                db.query(UsageMonth)
                .filter(
                    UsageMonth.organization_id == organization_id,
                    UsageMonth.user_id.in_(user_ids),
                    UsageMonth.period == period,
                )
                .all()
            )
            return {row.user_id: UsageTotalsModel.model_validate(row) for row in rows}

    def record_event(
        self,
        *,
        organization_id: str,
        user_id: str,
        usage: Optional[dict],
        model_id: Optional[str] = None,
        source: str = "chat",
        chat_id: Optional[str] = None,
        message_id: Optional[str] = None,
    ) -> Optional[UsageTotalsModel]:
        if not organization_id or not user_id:
            return None
        if not isinstance(usage, dict) or not usage:
            return None

        parsed = parse_provider_usage(usage)
        if not parsed["has_cost"]:
            log.warning(
                "usage missing provider cost; storing cost_usd=0 model=%s org=%s user=%s chat=%s message=%s",
                model_id,
                organization_id,
                user_id,
                chat_id,
                message_id,
            )

        period = current_period()
        now = int(time.time() * 1000)
        with get_db() as db:
            db.add(
                UsageEvent(
                    id=str(uuid.uuid4()),
                    created_at=now,
                    organization_id=organization_id,
                    user_id=user_id,
                    chat_id=chat_id,
                    message_id=message_id,
                    model_id=model_id,
                    source=source or "chat",
                    prompt_tokens=parsed["prompt_tokens"],
                    completion_tokens=parsed["completion_tokens"],
                    total_tokens=parsed["total_tokens"],
                    cached_tokens=parsed["cached_tokens"],
                    uncached_tokens=parsed["uncached_tokens"],
                    cost_usd=parsed["cost_usd"],
                    period=period,
                    raw=usage,
                )
            )
            self._bump_month(
                db,
                organization_id=organization_id,
                user_id=user_id,
                period=period,
                parsed=parsed,
            )
            self._bump_month(
                db,
                organization_id=organization_id,
                user_id=ORG_TOTAL_USER_ID,
                period=period,
                parsed=parsed,
            )
            db.commit()
        return self.get_month(organization_id, user_id, period)

    def _bump_month(self, db, *, organization_id, user_id, period, parsed) -> None:
        row = (
            db.query(UsageMonth)
            .filter_by(
                organization_id=organization_id, user_id=user_id, period=period
            )
            .first()
        )
        if not row:
            db.add(
                UsageMonth(
                    organization_id=organization_id,
                    user_id=user_id,
                    period=period,
                    prompt_tokens=parsed["prompt_tokens"],
                    completion_tokens=parsed["completion_tokens"],
                    total_tokens=parsed["total_tokens"],
                    cached_tokens=parsed["cached_tokens"],
                    uncached_tokens=parsed["uncached_tokens"],
                    cost_usd=parsed["cost_usd"],
                )
            )
            return
        row.prompt_tokens = int(row.prompt_tokens or 0) + parsed["prompt_tokens"]
        row.completion_tokens = int(row.completion_tokens or 0) + parsed[
            "completion_tokens"
        ]
        row.total_tokens = int(row.total_tokens or 0) + parsed["total_tokens"]
        row.cached_tokens = int(row.cached_tokens or 0) + parsed["cached_tokens"]
        row.uncached_tokens = int(row.uncached_tokens or 0) + parsed["uncached_tokens"]
        row.cost_usd = float(row.cost_usd or 0.0) + parsed["cost_usd"]

    def delete_for_organization(self, organization_id: str) -> None:
        with get_db() as db:
            db.query(UsageEvent).filter_by(organization_id=organization_id).delete()
            db.query(UsageMonth).filter_by(organization_id=organization_id).delete()
            db.commit()


Usage = UsageTable()
