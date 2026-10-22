"""Performance tests: event-loop blocking under production-like I/O latency.

Kept apart from backend/open_webui/test so scripts/perf_compare.py can run these
same tests against an older checkout of the app.
"""

import os
import sys
from pathlib import Path

# Before any test imports the app, so the engine opens a throwaway database.
if not os.environ.get("DATABASE_URL"):
    db_path = Path(os.environ.get("TMPDIR", "/tmp")) / "weather-skills-chat-perf.db"
    if db_path.exists():
        db_path.unlink()
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"

# perf_harness sits next to this file, whichever app checkout is on the path.
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Importing the app's config runs its database migrations. Do it before any
# test reads or writes a model, so every test starts from the full schema.
import open_webui.config  # noqa: E402,F401
