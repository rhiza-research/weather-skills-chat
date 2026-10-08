"""Which surfaces (chat interface, MCP endpoint) publish a catalog entry.

Each catalog entry stores a set of surfaces under SURFACES_KEY: interface only, endpoint only, or
both.
"""

import logging
from enum import StrEnum

log = logging.getLogger(__name__)

# Key every catalog producer sets on its entries.
SURFACES_KEY = "surfaces"

MISSING_KEY_MESSAGE = (
    "Catalog entry %r has no %r key; treating it as unpublished. The code that built this entry "
    "must set the key."
)


class Surface(StrEnum):
    """A place a catalog entry can be published."""

    INTERFACE = "interface"
    ENDPOINT = "endpoint"


INTERFACE_ONLY = frozenset({Surface.INTERFACE})
BOTH_SURFACES = frozenset({Surface.INTERFACE, Surface.ENDPOINT})
ENDPOINT_ONLY = frozenset({Surface.ENDPOINT})


def surfaces_for_tool_record(tool) -> frozenset:
    """Surfaces for a tool row: both for a skill (meta.manifest.kind == "skill"), else interface only."""
    manifest = (tool.meta.manifest if tool.meta else None) or {}
    return BOTH_SURFACES if manifest.get("kind") == "skill" else INTERFACE_ONLY


def publishes_to(name: str, entry: dict, surface: Surface) -> bool:
    """Whether the entry is published to the surface.

    An entry without SURFACES_KEY is logged at error level and treated as unpublished.
    """
    surfaces = entry.get(SURFACES_KEY)
    if surfaces is None:
        log.error(MISSING_KEY_MESSAGE, name, SURFACES_KEY)
        return False
    return surface in surfaces


def published_to(entries: dict, surface: Surface) -> dict:
    """The entries published to the surface, with their original keys."""
    return {
        name: entry
        for name, entry in entries.items()
        if publishes_to(name, entry, surface)
    }
