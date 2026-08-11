import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from starlette.requests import Request

from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.automations import Automations
from open_webui.utils.automation_runner import execute_automation

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MAIN"])

scheduler = AsyncIOScheduler()
_app = None


def _job_id(automation_id: str) -> str:
    return f"automation:{automation_id}"


def _make_request():
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/v1/automations/run",
        "raw_path": b"/api/v1/automations/run",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 0),
        "server": ("127.0.0.1", 80),
        "app": _app,
    }
    request = Request(scope)
    return request


async def _run_job(automation_id: str):
    try:
        request = _make_request()
        await execute_automation(request, automation_id, "schedule")
    except Exception:
        log.exception("Scheduled automation %s failed", automation_id)


def sync_automation_job(automation) -> None:
    job_id = _job_id(automation.id)
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    if not automation.enabled or not automation.cron:
        return
    try:
        trigger = CronTrigger.from_crontab(automation.cron)
    except Exception:
        log.exception("Invalid cron for automation %s: %s", automation.id, automation.cron)
        return
    scheduler.add_job(
        _run_job,
        trigger=trigger,
        id=job_id,
        args=[automation.id],
        replace_existing=True,
        misfire_grace_time=300,
    )


def remove_automation_job(automation_id: str) -> None:
    job_id = _job_id(automation_id)
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)


def start_scheduler(app) -> None:
    global _app
    _app = app
    if not scheduler.running:
        scheduler.start()
    for automation in Automations.get_enabled_scheduled():
        sync_automation_job(automation)


def shutdown_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
