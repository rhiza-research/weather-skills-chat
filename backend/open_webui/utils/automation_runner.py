import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.automations import AutomationRuns, Automations
from open_webui.models.chats import ChatForm, Chats
from open_webui.models.users import Users
from open_webui.utils.chat import generate_chat_completion

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MAIN"])


def _new_message(role: str, content: str, model: Optional[str] = None) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "parentId": None,
        "childrenIds": [],
        "role": role,
        "content": content,
        "timestamp": int(time.time()),
        **({"model": model, "done": True} if role == "assistant" else {}),
    }


async def execute_automation(request, automation_id: str, triggered_by: str):
    automation = Automations.get_automation_by_id(automation_id)
    if not automation:
        raise ValueError("Automation not found")

    owner_id = automation.user_id
    if triggered_by and triggered_by != "schedule":
        owner_id = triggered_by

    user = Users.get_user_by_id(owner_id)
    if not user:
        raise ValueError("Automation owner not found")

    run = AutomationRuns.insert_run(
        automation.id, status="running", triggered_by=triggered_by
    )
    title = f"{automation.name} — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
    user_message = _new_message("user", automation.prompt)
    history = {
        "messages": {user_message["id"]: user_message},
        "currentId": user_message["id"],
    }
    chat_blob = {
        "title": title,
        "models": [automation.model] if automation.model else [],
        "history": history,
        "messages": [user_message],
    }

    try:
        chat = Chats.insert_new_chat(
            owner_id,
            ChatForm(chat=chat_blob, team_id=automation.team_id),
        )
        if not chat:
            raise ValueError("Failed to create chat")
        AutomationRuns.update_run(run.id, chat_id=chat.id)

        form_data = {
            "model": automation.model,
            "messages": [{"role": "user", "content": automation.prompt}],
            "stream": False,
        }
        response = await generate_chat_completion(request, form_data=form_data, user=user)
        content = ""
        if isinstance(response, dict):
            content = (
                response.get("choices", [{}])[0].get("message", {}).get("content") or ""
            )
        assistant = _new_message("assistant", content, automation.model)
        assistant["parentId"] = user_message["id"]
        user_message["childrenIds"] = [assistant["id"]]
        history["messages"][user_message["id"]] = user_message
        history["messages"][assistant["id"]] = assistant
        history["currentId"] = assistant["id"]
        chat_blob["history"] = history
        chat_blob["messages"] = [user_message, assistant]
        Chats.update_chat_by_id(chat.id, chat_blob)
        return AutomationRuns.update_run(run.id, status="success", finished=True)
    except Exception as e:
        log.exception("Automation run failed")
        AutomationRuns.update_run(run.id, status="error", error=str(e), finished=True)
        raise
