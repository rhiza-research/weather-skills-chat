"""JSON column codec used by JSONField.

SQLite stores JSON as TEXT, so values are serialized strings.
Postgres JSON/JSONB columns are decoded by the driver into dict/list/scalars.
"""

from __future__ import annotations

import json
from typing import Any, Optional


def encode_json_field(value: Optional[Any]) -> Optional[str]:
    """Serialize a Python value for bind (both SQLite TEXT and Postgres JSON)."""
    if value is None:
        return None
    return json.dumps(value)


def decode_json_field(value: Optional[Any]) -> Any:
    """Accept either a JSON string (SQLite) or an already-decoded value (Postgres)."""
    if value is None or isinstance(value, (dict, list, bool, int, float)):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    return json.loads(value)
