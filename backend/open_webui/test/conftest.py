"""Isolate pytest from the developer's sqlite file.

Loaded before test modules import the app, so DATABASE_URL is already set
when the engine is created.
"""

import os
from pathlib import Path

if not os.environ.get("DATABASE_URL"):
    db_path = Path(os.environ.get("TMPDIR", "/tmp")) / "weather-skills-chat-pytest.db"
    if db_path.exists():
        db_path.unlink()
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
