"""User-facing chat write errors. Keep status codes out of the toast."""

CHAT_CONFLICT_MESSAGE = "Another user has edited the chat. Please try again."
CHAT_BUSY_MESSAGE = (
    "This chat is being edited in another window. Please try again shortly."
)
CHAT_SAVE_FAILED_MESSAGE = "The chat could not be saved. Please try again."
CHAT_TURN_REQUIRES_ID_MESSAGE = "A turn requires a saved chat id."


class ChatBusy(Exception):
    """The chat row lock timed out."""

    def __init__(self, message: str = CHAT_BUSY_MESSAGE):
        super().__init__(message)
        self.message = message


def conflict_detail(revision: int = 0, message: str = CHAT_CONFLICT_MESSAGE) -> dict:
    return {"message": message, "revision": revision}


def busy_detail() -> dict:
    return {"message": CHAT_BUSY_MESSAGE}
