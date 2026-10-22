"""Rows in the test database, through the app's own models."""

from __future__ import annotations

import uuid


def ensure_user(user_id: str = "perf-user"):
    from open_webui.models.users import Users

    user = Users.get_user_by_id(user_id)
    if user is None:
        user = Users.insert_new_user(
            user_id, "Perf User", f"{user_id}@example.com", role="user"
        )
    return user


def insert_chat(user_id: str, chat: dict) -> str:
    from open_webui.models.chats import ChatForm, Chats

    created = Chats.insert_new_chat(user_id, ChatForm(chat={**chat, "id": str(uuid.uuid4())}))
    return created.id


def app_with(router, prefix: str, user):
    """A FastAPI app serving one router as ``user``."""
    from fastapi import FastAPI

    from open_webui.utils.auth import get_verified_user

    app = FastAPI()
    app.include_router(router, prefix=prefix)
    app.dependency_overrides[get_verified_user] = lambda: user
    return app


def main_app(user):
    """The full app from main.py, serving every route as ``user``."""
    import main
    from open_webui.utils.auth import get_current_user, get_verified_user

    main.app.dependency_overrides[get_verified_user] = lambda: user
    main.app.dependency_overrides[get_current_user] = lambda: user
    return main.app


def asgi_client(app):
    """An httpx client that runs ``app`` on the caller's event loop."""
    import httpx

    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://perf", timeout=120
    )
