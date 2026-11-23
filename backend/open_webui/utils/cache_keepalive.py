"""Keeps a chat's prompt cache alive between its model calls.

The provider keeps a cached prompt for five minutes from the start of the
call that wrote or last read it. When INTERVAL_S pass after a chat's last
model call started and no new call has, the call is re-sent capped at one
output token, which reads the cache and restarts its five minutes. While the chat's reply
is running this goes on; once the reply has ended it happens at most
IDLE_COUNT times, while the user reads and answers.
"""

import asyncio
import logging
import os
import time

from open_webui.env import SRC_LOG_LEVELS
from open_webui.tasks import list_task_ids_by_chat_id

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MAIN"])

INTERVAL_S = 270
IDLE_COUNT = int(os.environ.get("CACHE_KEEPALIVE_IDLE_COUNT", "3"))

# shortcut: per process. With several replicas a chat's next call can land on
# another one and leave this timer sending up to IDLE_COUNT cache reads; move
# it to Redis if that cost shows up.
_timers: dict[str, asyncio.Task] = {}
# The provider keeps a cached prompt this long from the start of its last read.
CACHE_TTL_S = 300
# chat id -> [its last cached reply call, time.monotonic() the cache was last
# written or read]. Kept while the chat has a timer.
_last_calls: dict[str, list] = {}


def restart(chat_id: str, send, source: str, last_call=None) -> None:
    """A chat's model call is starting: replace the chat's timer.

    ``send`` re-sends the call capped at one token; without it the chat gets no
    timer. A scheduled task's run (``source`` "automation") gets no
    keep-alives once it ends, since nobody answers it. ``last_call`` is the
    call being sent, kept for warm_call.
    """
    old = _timers.pop(chat_id, None)
    if old is not None:
        old.cancel()
    _last_calls.pop(chat_id, None)
    if last_call is not None:
        _last_calls[chat_id] = [last_call, time.monotonic()]
    if send is not None:
        idle_count = 0 if source == "automation" else IDLE_COUNT
        _timers[chat_id] = asyncio.create_task(_run(chat_id, send, idle_count))


def touch(chat_id: str) -> None:
    """A request just read the chat's cached prompt, which restarts its lifetime."""
    entry = _last_calls.get(chat_id)
    if entry is not None:
        entry[1] = time.monotonic()


def warm_call(chat_id: str, margin_s: float = 15):
    """The chat's last cached reply call while its cache is alive.

    margin_s leaves time for a request to start before the cache expires.
    """
    entry = _last_calls.get(chat_id)
    if entry is None or time.monotonic() - entry[1] > CACHE_TTL_S - margin_s:
        return None
    return entry[0]


async def _run(chat_id: str, send, idle_count: int) -> None:
    idle_sent = 0
    try:
        while True:
            await asyncio.sleep(INTERVAL_S)
            if not list_task_ids_by_chat_id(chat_id):
                if idle_sent >= idle_count:
                    return
                idle_sent += 1
            await send()
    except asyncio.CancelledError:
        raise
    except Exception:
        log.warning(
            "Cache keep-alive for chat %s failed; none more until its next call",
            chat_id,
            exc_info=True,
        )
    finally:
        if _timers.get(chat_id) is asyncio.current_task():
            del _timers[chat_id]
            _last_calls.pop(chat_id, None)
