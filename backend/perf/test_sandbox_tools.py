"""Built-in tools that work in the chat's sandbox on JuiceFS (#1, #2).

Every path lookup goes through chat_sandbox(), which creates the chat's
folders and re-owns them on each call (#1). The tools then do their file work
on the event loop: making folders, copying Zarr stores, waiting for and
reading images, reading email attachments (#2).
"""

import asyncio
import smtplib
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

from perf_harness import LoopProbe, check_budget, db_delay, fs_delay, record
from perf_harness.app_data import call_tool, ensure_user, insert_chat
from perf_harness.data import big_chat, png_with_provenance

CALLS = 30
# Between tool calls the model is generating the next one.
MODEL_GAP_S = 0.01
# A Resend SMTP send: connect, TLS and EHLO measured at 293 ms from the staging
# pod, plus login and the message (a few more ~55 ms round trips).
SMTP_SEND_S = 0.55


def _chat(tmp_path):
    juicefs = tmp_path / "juicefs"
    artifacts = juicefs / "artifacts"
    user = ensure_user()
    chat_id = insert_chat(user.id, big_chat(150_000))
    return juicefs, artifacts, user, chat_id


def _sandbox(artifacts, juicefs):
    return patch("open_webui.utils.artifacts.ARTIFACTS_DIR", artifacts), db_delay(), fs_delay([juicefs])


def test_create_folder_calls(tmp_path):
    from open_webui.utils import builtin_tools

    juicefs, artifacts, user, chat_id = _chat(tmp_path)

    async def run():
        async with LoopProbe() as probe:
            for i in range(CALLS):
                out = await call_tool(
                    builtin_tools.create_folder,
                    path=f"plots/week_{i}", __user__={"id": user.id}, __metadata__={"chat_id": chat_id}
                )
                assert "week_" in out
                await asyncio.sleep(MODEL_GAP_S)
        return probe.stats

    a, b, c = _sandbox(artifacts, juicefs)
    with a, b, c:
        stats = asyncio.run(run())
    record(f"sandbox tools: {CALLS} create_folder calls", stats)
    check_budget(stats, max_lag_ms=25, blocked_pct=10, pending="#1 chat_sandbox, #2 tool file work")


def test_copy_zarr_store_into_intermediate_results(tmp_path):
    from open_webui.utils import builtin_tools

    juicefs, artifacts, user, chat_id = _chat(tmp_path)
    store = artifacts / chat_id / "runs" / "precip.zarr"
    for var in ("precip", "time", "latitude", "longitude"):
        (store / var).mkdir(parents=True)
        (store / var / ".zarray").write_text("{}")
        for i in range(100):
            (store / var / f"0.{i}").write_bytes(b"\0" * 16_384)
    (store / ".zgroup").write_text('{"zarr_format": 2}')

    async def run():
        async with LoopProbe() as probe:
            out = await call_tool(
                builtin_tools.copy_intermediate_result,
                path="runs/precip.zarr",
                direction="in",
                __user__={"id": user.id},
                __metadata__={"chat_id": chat_id},
            )
            assert "precip.zarr" in out, out
        return probe.stats

    a, b, c = _sandbox(artifacts, juicefs)
    with a, b, c:
        stats = asyncio.run(run())
    record("sandbox tools: copy a 400-chunk Zarr store to intermediate results", stats)
    check_budget(stats, max_lag_ms=50, pending="#1 chat_sandbox, #2 tool file work")


def test_display_image_while_the_skill_writes_it(tmp_path):
    """The model asks to show a plot the skill is still writing."""
    from open_webui.utils import builtin_tools

    juicefs, artifacts, user, chat_id = _chat(tmp_path)
    (artifacts / chat_id / "plots").mkdir(parents=True)
    target = artifacts / chat_id / "plots" / "weekly.png"
    png = png_with_provenance(size_bytes=4_000_000)

    def skill_writes_later():
        time.sleep(1.0)
        target.write_bytes(png)

    async def run():
        writer = threading.Thread(target=skill_writes_later)
        async with LoopProbe() as probe:
            writer.start()
            out = await call_tool(
                builtin_tools.display_image,
                path="plots/weekly.png", __user__={"id": user.id}, __metadata__={"chat_id": chat_id}
            )
        writer.join()
        assert "weekly.png" in str(out)
        return probe.stats

    a, b, c = _sandbox(artifacts, juicefs)
    with a, b, c:
        stats = asyncio.run(run())
    record("sandbox tools: display_image of a 4 MB plot written after 1 s", stats)
    check_budget(stats, max_lag_ms=25, pending="#1 chat_sandbox, #2 tool file work")


class _SMTP:
    def __init__(self, *args, **kwargs):
        time.sleep(SMTP_SEND_S)

    def __getattr__(self, name):
        return lambda *args, **kwargs: (250, b"ok")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_send_email_with_attachments(tmp_path):
    from open_webui.utils import builtin_tools

    juicefs, artifacts, user, chat_id = _chat(tmp_path)
    plots = artifacts / chat_id / "plots"
    plots.mkdir(parents=True)
    for name in ("weekly.png", "monthly.png", "anomaly.png"):
        (plots / name).write_bytes(png_with_provenance(size_bytes=3_000_000))
    config = SimpleNamespace(
        EMAIL_TOOL_SMTP_HOST="smtp.test",
        EMAIL_TOOL_SMTP_PORT=465,
        EMAIL_TOOL_SMTP_USERNAME="resend",
        EMAIL_TOOL_SMTP_PASSWORD="test-password",
        EMAIL_TOOL_SMTP_USE_TLS=True,
        EMAIL_TOOL_FROM_EMAIL="help@example.com",
        WEBUI_URL="https://chat.test",
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(config=config)))

    async def run():
        async with LoopProbe() as probe:
            out = await call_tool(
                builtin_tools.send_email,
                to=user.email,
                subject="Weekly rainfall",
                body="Plots attached.",
                attachments=["plots/weekly.png", "plots/monthly.png", "plots/anomaly.png"],
                __user__={"id": user.id},
                __metadata__={"chat_id": chat_id},
                __request__=request,
            )
        assert "sent" in out.lower(), out
        return probe.stats

    a, b, c = _sandbox(artifacts, juicefs)
    with a, b, c, patch.object(smtplib, "SMTP_SSL", _SMTP), patch.object(smtplib, "SMTP", _SMTP):
        stats = asyncio.run(run())
    record("sandbox tools: send_email with three 3 MB attachments", stats)
    check_budget(stats, max_lag_ms=25, pending="#2 tool file work")
