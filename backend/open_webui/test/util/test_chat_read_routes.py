"""Routes that read a whole chat run in FastAPI's threadpool, off the event loop."""

import inspect
import unittest

# Each loads the whole chat (and the chat route returns it), so as plain
# functions both the read and the response are built on a worker thread.
CHAT_READ_ROUTES = [
    "/api/v1/chats/{id}",
    "/api/v1/chats/{id}/tags",
    "/api/v1/chats/{id}/pinned",
]


class ChatReadRoutesTest(unittest.TestCase):
    def test_chat_read_handlers_are_plain_functions(self):
        from fastapi.routing import APIRoute

        import main

        handlers = {
            route.path: route.endpoint
            for route in main.app.routes
            if isinstance(route, APIRoute) and "GET" in route.methods
        }
        for path in CHAT_READ_ROUTES:
            self.assertIn(path, handlers)
            self.assertFalse(
                inspect.iscoroutinefunction(handlers[path]),
                f"{path} runs on the event loop",
            )


if __name__ == "__main__":
    unittest.main()
