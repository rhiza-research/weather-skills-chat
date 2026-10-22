"""The app builds the Langfuse client at startup, off the event loop."""

import threading
import unittest
from unittest.mock import MagicMock, patch


class LangfuseStartupTest(unittest.IsolatedAsyncioTestCase):
    async def test_client_is_built_on_a_worker_thread_before_serving(self):
        import main

        threads = []

        def get_client():
            threads.append(threading.current_thread())

        async def no_cleanup():
            return None

        with patch.object(main, "get_langfuse_client", get_client), patch.object(
            main, "start_logger"
        ), patch.object(main, "periodic_usage_pool_cleanup", no_cleanup), patch.object(
            main, "ensure_retrieval_models"
        ), patch.object(main, "_resync_skill_packs"), patch(
            "open_webui.utils.bootstrap.bootstrap_admin_user"
        ), patch("open_webui.utils.automation_scheduler.start_scheduler"), patch(
            "open_webui.utils.automation_scheduler.shutdown_scheduler"
        ), patch.object(main, "shutdown_langfuse", MagicMock()):
            async with main.lifespan(main.app):
                self.assertEqual(len(threads), 1)

        self.assertIsNot(threads[0], threading.main_thread())


if __name__ == "__main__":
    unittest.main()
