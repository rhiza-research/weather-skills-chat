"""The memories router has no unauthenticated embedding debug route."""

import unittest


class MemoriesRoutesTest(unittest.TestCase):
    def test_no_embedding_debug_route(self):
        from fastapi.routing import APIRoute

        import main

        paths = {route.path for route in main.app.routes if isinstance(route, APIRoute)}
        self.assertNotIn("/api/v1/memories/ef", paths)
        self.assertIn("/api/v1/memories/", paths)


if __name__ == "__main__":
    unittest.main()
