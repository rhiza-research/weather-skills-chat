"""Size limits on endpoint tool results.

Applied to every endpoint result by serialized size, regardless of which tool produced it. The chat
interface does not apply these limits.
"""

import json
import logging

log = logging.getLogger(__name__)

# Maximum serialized size of one tool result: 128 KiB, about 32,000 tokens at four bytes per token.
# Same value as the sibling MCP service.
MAX_RESULT_BYTES = 131_072

# Maximum characters kept from each of a skill run's stdout and stderr. Same value as the sibling
# MCP service's stdout cap.
MAX_RUN_OUTPUT_CHARACTERS = 20_000

# Listing entries that fit in MAX_RESULT_BYTES at the longest measured entry size. Not enforced
# separately; MAX_RESULT_BYTES enforces it.
MAX_LISTING_ENTRIES = 1_000

# Longest listing entry measured in this project's artifact trees (average about 55 bytes).
LONGEST_MEASURED_LISTING_ENTRY_BYTES = 91

SHORTENED_NOTICE = (
    "\n\n[Shortened. {returned} of {total} bytes are above; the rest was not returned. Request a "
    "narrower path, or fetch the artifact with get_artifact.]"
)

RUN_OUTPUT_SHORTENED_NOTICE = (
    "\n[Shortened. {returned} of {total} characters of {stream} are above.]"
)

# Keys of a skill run result that hold its output. The runner sets both on success and failure.
RUN_OUTPUT_KEYS = ("stdout", "stderr")


def _serialized(value) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, default=str)
    except Exception:
        return str(value)


def within_bounds(value):
    """Return (value, False) if it fits in MAX_RESULT_BYTES, else (truncated string, True).

    A truncated result is the serialized value cut to fit, followed by SHORTENED_NOTICE.
    """
    serialized = _serialized(value)
    total = len(serialized.encode("utf-8"))
    if total <= MAX_RESULT_BYTES:
        return value, False

    # The notice reports the bytes kept, not MAX_RESULT_BYTES, because the notice itself counts
    # toward the limit.
    room = max(MAX_RESULT_BYTES - len(_notice_width(total)), 0)
    kept_bytes = serialized.encode("utf-8")[:room]
    kept = kept_bytes.decode("utf-8", errors="ignore")
    notice = SHORTENED_NOTICE.format(returned=len(kept.encode("utf-8")), total=total)
    log.info("Shortened an endpoint result from %d to %d bytes", total, len(kept_bytes))
    return kept + notice, True


def _notice_width(total: int) -> bytes:
    """The notice formatted with its largest possible numbers, used to reserve room for it."""
    return SHORTENED_NOTICE.format(returned=total, total=total).encode("utf-8")


def within_run_output_bound(value):
    """Truncate stdout and stderr in a run result to MAX_RUN_OUTPUT_CHARACTERS each.

    Other fields are kept. A value that is not a dict is returned unchanged.
    """
    if not isinstance(value, dict):
        return value
    shortened = None
    for key in RUN_OUTPUT_KEYS:
        stream = value.get(key)
        if not isinstance(stream, str) or len(stream) <= MAX_RUN_OUTPUT_CHARACTERS:
            continue
        if shortened is None:
            shortened = dict(value)
        kept = stream[:MAX_RUN_OUTPUT_CHARACTERS]
        shortened[key] = kept + RUN_OUTPUT_SHORTENED_NOTICE.format(
            returned=len(kept), total=len(stream), stream=key
        )
        log.info(
            "Shortened a run's %s from %d to %d characters",
            key,
            len(stream),
            len(kept),
        )
    return value if shortened is None else shortened
