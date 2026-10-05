import logging
import time

from fastapi.testclient import TestClient
from sqlalchemy import text


log = logging.getLogger(__name__)


_fast_api_client = None


def get_fast_api_client():
    global _fast_api_client
    if _fast_api_client is None:
        from main import app

        # Stay entered for the whole run. Leaving the context closes the event
        # loop, and the next test class cannot open another client.
        _fast_api_client = TestClient(app)
        _fast_api_client.__enter__()
    return _fast_api_client


class AbstractIntegrationTest:
    BASE_PATH = None

    def create_url(self, path="", query_params=None):
        if self.BASE_PATH is None:
            raise Exception("BASE_PATH is not set")
        parts = self.BASE_PATH.split("/")
        parts = [part.strip() for part in parts if part.strip() != ""]
        path_parts = path.split("/")
        path_parts = [part.strip() for part in path_parts if part.strip() != ""]
        query_parts = ""
        if query_params:
            query_parts = "&".join(
                [f"{key}={value}" for key, value in query_params.items()]
            )
            query_parts = f"?{query_parts}"
        url = "/".join(parts + path_parts)
        # Collection routes are registered with a trailing slash. Without it
        # the request falls through to the frontend and comes back as HTML.
        if (path == "" or path.endswith("/")) and not url.endswith("/"):
            url += "/"
        return url + query_parts

    @classmethod
    def setup_class(cls):
        pass

    def setup_method(self):
        pass

    @classmethod
    def teardown_class(cls):
        pass

    def teardown_method(self):
        pass


class AbstractPostgresTest(AbstractIntegrationTest):
    # The app runs on the database in DATABASE_URL, which conftest.py points at a
    # temporary sqlite file.
    @classmethod
    def setup_class(cls):
        super().setup_class()
        cls.fast_api_client = get_fast_api_client()

    def _check_db_connection(self):
        from open_webui.internal.db import Session

        retries = 10
        while retries > 0:
            try:
                Session.execute(text("SELECT 1"))
                Session.commit()
                break
            except Exception as e:
                Session.rollback()
                log.warning(e)
                time.sleep(3)
                retries -= 1

    def setup_method(self):
        super().setup_method()
        self._check_db_connection()

    def teardown_method(self):
        from open_webui.internal.db import Session

        # rollback everything not yet committed
        Session.commit()

        # Clear rows. DELETE works on the sqlite engine these tests actually
        # use and on postgres.
        bind = Session.get_bind()
        if bind.dialect.name == "sqlite":
            Session.execute(text("PRAGMA foreign_keys=OFF"))
        tables = [
            "auth",
            "invitation",
            "chat",
            "chatidtag",
            "document",
            "memory",
            "model",
            "org_catalog_override",
            "prompt",
            "tag",
            '"user"',
        ]
        for table in tables:
            Session.execute(text(f"DELETE FROM {table}"))
        Session.commit()
