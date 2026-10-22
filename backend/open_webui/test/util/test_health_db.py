"""GET /health/db checks the database off the event loop."""

import threading
import unittest
from contextlib import contextmanager
from unittest.mock import patch

import httpx


class HealthDbTest(unittest.IsolatedAsyncioTestCase):
    async def test_database_ping_runs_on_a_worker_thread_and_closes_its_session(self):
        import main

        threads = []
        closed = []
        real_get_db = main.get_db

        @contextmanager
        def get_db():
            threads.append(threading.current_thread())
            with real_get_db() as db:
                yield db
            closed.append(True)

        transport = httpx.ASGITransport(app=main.app)
        with patch.object(main, "get_db", get_db):
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/health/db")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": True})
        self.assertEqual(len(threads), 1)
        self.assertIsNot(threads[0], threading.current_thread())
        self.assertEqual(closed, [True])

    async def test_an_unreachable_database_fails_readiness(self):
        import main

        @contextmanager
        def down():
            raise ConnectionError("database unreachable")
            yield

        transport = httpx.ASGITransport(app=main.app, raise_app_exceptions=False)
        with patch.object(main, "get_db", down):
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/health/db")

        self.assertEqual(response.status_code, 500)
