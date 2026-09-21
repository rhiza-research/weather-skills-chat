import logging
import time
from typing import Optional

from open_webui.internal.db import Base, JSONField, get_db
from open_webui.models.users import Users, UserResponse
from open_webui.env import SRC_LOG_LEVELS
from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, Column, String, Text, JSON

from open_webui.utils.access_control import has_access


log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

####################
# Tools DB Schema
####################


class Tool(Base):
    __tablename__ = "tool"

    id = Column(String, primary_key=True)
    user_id = Column(String)
    name = Column(Text)
    content = Column(Text)
    specs = Column(JSONField)
    meta = Column(JSONField)
    valves = Column(JSONField)

    access_control = Column(JSON, nullable=True)  # Controls data access levels.
    # Defines access control rules for this entry.
    # - `None`: Public access, available to all users with the "user" role.
    # - `{}`: Private access, restricted exclusively to the owner.
    # - Custom permissions: Specific access control for reading and writing;
    #   Can specify group or user-level restrictions:
    #   {
    #      "read": {
    #          "group_ids": ["group_id1", "group_id2"],
    #          "user_ids":  ["user_id1", "user_id2"]
    #      },
    #      "write": {
    #          "group_ids": ["group_id1", "group_id2"],
    #          "user_ids":  ["user_id1", "user_id2"]
    #      }
    #   }

    updated_at = Column(BigInteger)
    created_at = Column(BigInteger)


class ToolMeta(BaseModel):
    description: Optional[str] = None
    manifest: Optional[dict] = {}


class ToolModel(BaseModel):
    id: str
    user_id: str
    name: str
    content: str
    specs: list[dict]
    meta: ToolMeta
    access_control: Optional[dict] = None

    updated_at: int  # timestamp in epoch
    created_at: int  # timestamp in epoch

    model_config = ConfigDict(from_attributes=True)


####################
# Forms
####################


class ToolUserModel(ToolModel):
    user: Optional[UserResponse] = None


class ToolCatalogModel(BaseModel):
    """Tool row without `content` — one SELECT for access checks and specs."""

    id: str
    user_id: str
    name: str
    specs: list[dict]
    meta: ToolMeta
    access_control: Optional[dict] = None
    valves: Optional[dict] = None
    updated_at: int
    created_at: int


class ToolResponse(BaseModel):
    id: str
    user_id: str
    name: str
    meta: ToolMeta
    access_control: Optional[dict] = None
    updated_at: int  # timestamp in epoch
    created_at: int  # timestamp in epoch


class ToolUserResponse(ToolResponse):
    user: Optional[UserResponse] = None


class ToolForm(BaseModel):
    id: str
    name: str
    content: str
    meta: ToolMeta
    access_control: Optional[dict] = None


class ToolValves(BaseModel):
    valves: Optional[dict] = None


class ToolsTable:
    def insert_new_tool(
        self, user_id: str, form_data: ToolForm, specs: list[dict]
    ) -> Optional[ToolModel]:
        with get_db() as db:
            tool = ToolModel(
                **{
                    **form_data.model_dump(),
                    "specs": specs,
                    "user_id": user_id,
                    "updated_at": int(time.time()),
                    "created_at": int(time.time()),
                }
            )

            try:
                result = Tool(**tool.model_dump())
                db.add(result)
                db.commit()
                db.refresh(result)
                if result:
                    return ToolModel.model_validate(result)
                else:
                    return None
            except Exception as e:
                log.exception(f"Error creating a new tool: {e}")
                return None

    def get_tool_by_id(self, id: str) -> Optional[ToolModel]:
        try:
            with get_db() as db:
                tool = db.get(Tool, id)
                return ToolModel.model_validate(tool)
        except Exception:
            return None

    def get_tool_catalog(self) -> list[ToolCatalogModel]:
        """All tools in one query, omitting wrapper `content`."""
        from open_webui.utils.chat_timing import log_timing

        t0 = time.perf_counter()
        with get_db() as db:
            rows = (
                db.query(
                    Tool.id,
                    Tool.user_id,
                    Tool.name,
                    Tool.specs,
                    Tool.meta,
                    Tool.access_control,
                    Tool.valves,
                    Tool.updated_at,
                    Tool.created_at,
                )
                .order_by(Tool.updated_at.desc())
                .all()
            )
            tools = []
            for row in rows:
                meta = row.meta or {}
                if not isinstance(meta, ToolMeta):
                    try:
                        meta = ToolMeta.model_validate(meta) if meta else ToolMeta()
                    except Exception:
                        meta = ToolMeta()
                tools.append(
                    ToolCatalogModel(
                        id=row.id,
                        user_id=row.user_id,
                        name=row.name or "",
                        specs=row.specs or [],
                        meta=meta,
                        access_control=row.access_control,
                        valves=row.valves,
                        updated_at=row.updated_at or 0,
                        created_at=row.created_at or 0,
                    )
                )
        log_timing(
            "db.Tools.get_tool_catalog",
            time.perf_counter() - t0,
            n=len(tools),
        )
        return tools

    def get_tools(self) -> list[ToolUserModel]:
        from open_webui.utils.chat_timing import log_timing

        t0 = time.perf_counter()
        catalog = self.get_tool_catalog()
        t_users = time.perf_counter()
        user_ids = list({tool.user_id for tool in catalog if tool.user_id})
        users_by_id = (
            {user.id: user for user in Users.get_users_by_user_ids(user_ids)}
            if user_ids
            else {}
        )
        tools = []
        for tool in catalog:
            user = users_by_id.get(tool.user_id)
            tools.append(
                ToolUserModel.model_validate(
                    {
                        "id": tool.id,
                        "user_id": tool.user_id,
                        "name": tool.name,
                        "content": "",
                        "specs": tool.specs,
                        "meta": tool.meta,
                        "access_control": tool.access_control,
                        "updated_at": tool.updated_at,
                        "created_at": tool.created_at,
                        "user": user.model_dump() if user else None,
                    }
                )
            )
        log_timing(
            "db.Tools.get_tools",
            time.perf_counter() - t0,
            n=len(tools),
            users_batch_s=f"{time.perf_counter() - t_users:.3f}",
            users_n=len(users_by_id),
        )
        return tools

    def get_tools_by_user_id(
        self, user_id: str, permission: str = "write"
    ) -> list[ToolUserModel]:
        tools = self.get_tools()

        return [
            tool
            for tool in tools
            if tool.user_id == user_id
            or has_access(user_id, permission, tool.access_control)
        ]

    def get_tool_valves_by_id(self, id: str) -> Optional[dict]:
        try:
            with get_db() as db:
                tool = db.get(Tool, id)
                return tool.valves if tool.valves else {}
        except Exception as e:
            log.exception(f"Error getting tool valves by id {id}: {e}")
            return None

    def update_tool_valves_by_id(self, id: str, valves: dict) -> Optional[ToolValves]:
        try:
            with get_db() as db:
                db.query(Tool).filter_by(id=id).update(
                    {"valves": valves, "updated_at": int(time.time())}
                )
                db.commit()
                return self.get_tool_by_id(id)
        except Exception:
            return None

    def get_user_valves_by_id_and_user_id(
        self, id: str, user_id: str
    ) -> Optional[dict]:
        try:
            user = Users.get_user_by_id(user_id)
            user_settings = user.settings.model_dump() if user.settings else {}

            # Check if user has "tools" and "valves" settings
            if "tools" not in user_settings:
                user_settings["tools"] = {}
            if "valves" not in user_settings["tools"]:
                user_settings["tools"]["valves"] = {}

            return user_settings["tools"]["valves"].get(id, {})
        except Exception as e:
            log.exception(
                f"Error getting user values by id {id} and user_id {user_id}: {e}"
            )
            return None

    def update_user_valves_by_id_and_user_id(
        self, id: str, user_id: str, valves: dict
    ) -> Optional[dict]:
        try:
            user = Users.get_user_by_id(user_id)
            user_settings = user.settings.model_dump() if user.settings else {}

            # Check if user has "tools" and "valves" settings
            if "tools" not in user_settings:
                user_settings["tools"] = {}
            if "valves" not in user_settings["tools"]:
                user_settings["tools"]["valves"] = {}

            user_settings["tools"]["valves"][id] = valves

            # Update the user settings in the database
            Users.update_user_by_id(user_id, {"settings": user_settings})

            return user_settings["tools"]["valves"][id]
        except Exception as e:
            log.exception(
                f"Error updating user valves by id {id} and user_id {user_id}: {e}"
            )
            return None

    def update_tool_by_id(self, id: str, updated: dict) -> Optional[ToolModel]:
        from open_webui.utils.chat_timing import log_timing

        t0 = time.perf_counter()
        try:
            with get_db() as db:
                tool = db.query(Tool).filter_by(id=id).first()
                if not tool:
                    return None
                for key, value in updated.items():
                    setattr(tool, key, value)
                tool.updated_at = int(time.time())
                db.add(tool)
                db.commit()
                db.refresh(tool)
                result = ToolModel.model_validate(tool)
            content = updated.get("content")
            log_timing(
                "db.Tools.update_tool_by_id",
                time.perf_counter() - t0,
                tool_id=id,
                content_bytes=len(content) if isinstance(content, str) else None,
            )
            return result
        except Exception:
            return None

    def delete_tool_by_id(self, id: str) -> bool:
        try:
            with get_db() as db:
                db.query(Tool).filter_by(id=id).delete()
                db.commit()

                return True
        except Exception:
            return False


Tools = ToolsTable()
