"""Preparing a chat request keeps its database work off the event loop, and
the secret and tool access checks read memberships once."""

import asyncio
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import main
from open_webui.models.secrets import SecretModel
from open_webui.utils import access_control, middleware
from open_webui.utils import secrets as secrets_util
from open_webui.utils import tools as tools_util


def _user(role="user"):
    return SimpleNamespace(id="u1", email="u1@example.com", name="U", role=role)


class ChatCompletionRouteTest(unittest.IsolatedAsyncioTestCase):
    async def test_the_request_is_checked_on_a_worker_thread(self):
        loop_thread = threading.current_thread()
        ran_on = {}

        def prepare(request, form_data, user, organization_id):
            ran_on["thread"] = threading.current_thread()
            metadata = {"chat_id": "chat-1", "message_id": "m1", "organization_id": "org-1"}
            return main.PreparedChat(
                model={"id": "m"}, metadata=metadata, direct=False, tasks=None, turn=None
            )

        def start_job(coro, id):
            coro.close()
            return "task-1", None

        request = SimpleNamespace(state=SimpleNamespace())
        with patch.object(main, "prepare_chat_completion", side_effect=prepare), patch.object(
            main, "create_task", side_effect=start_job
        ):
            result = await main.chat_completion(
                request, {"model": "m", "chat_id": "chat-1"}, _user(), "org-1"
            )

        self.assertEqual(result, {"status": True, "task_id": "task-1"})
        self.assertIsNot(ran_on["thread"], loop_thread)
        self.assertEqual(request.state.metadata["organization_id"], "org-1")

    async def test_other_errors_are_a_bad_request(self):
        request = SimpleNamespace(state=SimpleNamespace())
        with patch.object(
            main, "prepare_chat_completion", side_effect=ValueError("Model not found")
        ):
            with self.assertRaises(main.HTTPException) as raised:
                await main.chat_completion(request, {"model": "m"}, _user(), "org-1")
        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(raised.exception.detail, "Model not found")


class PrepareChatCompletionTest(unittest.TestCase):
    def _patches(self):
        model_info = SimpleNamespace(params=SimpleNamespace(model_dump=lambda: {}))
        return [
            patch.object(main, "require_owned_chat", return_value=None),
            patch.object(main, "chat_organization_id", return_value="org-1"),
            patch.object(main, "remember_catalog_model", return_value={"id": "m"}),
            patch.object(main.Models, "get_model_by_id", return_value=model_info),
            patch.object(main, "check_model_access"),
            patch.object(main, "check_usage_caps"),
        ]

    def test_a_turn_error_is_recorded_on_the_reply_message(self):
        request = SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(config=SimpleNamespace()))
        )
        form = {
            "model": "m",
            "chat_id": "chat-1",
            "id": "m1",
            "turn": {"user_message": {}},
        }
        patches = self._patches() + [
            patch(
                "open_webui.utils.chat_turns.prepare_completion_messages",
                side_effect=ValueError("bad history"),
            ),
            patch.object(main.Chats, "upsert_message_to_chat_by_id_and_message_id"),
        ]
        mocks = [p.start() for p in patches]
        self.addCleanup(lambda: [p.stop() for p in reversed(patches)])

        with self.assertRaisesRegex(ValueError, "bad history"):
            main.prepare_chat_completion(request, form, _user(), "org-1")
        mocks[-1].assert_called_once_with(
            "chat-1", "m1", {"error": {"content": "bad history"}}
        )

    def test_returns_the_metadata_and_pops_the_request_fields(self):
        request = SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(config=SimpleNamespace()))
        )
        form = {"model": "m", "chat_id": "chat-1", "id": "m1", "background_tasks": {"x": 1}}
        patches = self._patches()
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in reversed(patches)])

        prepared = main.prepare_chat_completion(request, form, _user(), "org-1")

        self.assertEqual(prepared.metadata["chat_id"], "chat-1")
        self.assertEqual(prepared.metadata["organization_id"], "org-1")
        self.assertEqual(prepared.tasks, {"x": 1})
        self.assertFalse(prepared.direct)
        self.assertNotIn("chat_id", form)
        self.assertIs(form["metadata"], prepared.metadata)


class ProcessChatPayloadTest(unittest.IsolatedAsyncioTestCase):
    async def test_both_database_phases_run_on_worker_threads(self):
        loop_thread = threading.current_thread()
        ran_on = {}

        def start(form_data, model):
            ran_on["start"] = threading.current_thread()
            return form_data, []

        def load(request, user, metadata, tool_extra, model_id, clock):
            ran_on["context"] = threading.current_thread()
            return middleware.PayloadContext(
                tools={}, tool_ids=None, secret_hint="", model_params=None, preferences="Use mm."
            )

        config = SimpleNamespace(TASK_MODEL="", TASK_MODEL_EXTERNAL="", RENDERING_PROMPT="")
        request = SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(config=config, MODELS={"m": {"id": "m"}})),
            state=SimpleNamespace(),
        )
        form = {"model": "m", "messages": [{"role": "user", "content": "Rain?"}]}
        with patch.object(middleware, "start_chat_payload", side_effect=start), patch.object(
            middleware, "load_payload_context", side_effect=load
        ), patch.object(
            middleware, "process_pipeline_inlet_filter", AsyncMock(side_effect=lambda r, f, u, m: f)
        ), patch.object(
            middleware,
            "chat_completion_files_handler",
            AsyncMock(side_effect=lambda r, f, u: (f, {})),
        ):
            form_data, metadata, events = await middleware.process_chat_payload(
                request, form, _user(), {"chat_id": "chat-1", "organization_id": "org-1"}, {"id": "m"}
            )

        self.assertIsNot(ran_on["start"], loop_thread)
        self.assertIsNot(ran_on["context"], loop_thread)
        self.assertIn("Use mm.", str(form_data["messages"]))


class SecretMetadataTest(unittest.TestCase):
    def _row(self, i, user_id, visibility):
        return SecretModel(
            id=f"s{i}",
            name=f"KEY_{i}",
            user_id=user_id,
            organization_id="org-1",
            visibility=visibility,
            created_at=0,
            updated_at=0,
        )

    def test_rows_are_not_reread_and_admin_is_checked_once(self):
        rows = [self._row(i, "u1", "private") for i in range(4)]
        rows += [self._row(i, "u2", "organization") for i in range(4, 8)]
        with patch.object(secrets_util.Secrets, "list_for_org", return_value=rows), patch.object(
            secrets_util.Secrets, "get_by_id"
        ) as get_by_id, patch.object(secrets_util, "is_org_admin", return_value=True) as is_admin:
            items = secrets_util.list_secret_metadata(_user(), "org-1")

        get_by_id.assert_not_called()
        is_admin.assert_called_once_with("org-1", "u1")
        self.assertTrue(all(item["can_manage"] for item in items))

    def test_no_admin_check_when_the_user_owns_every_row(self):
        rows = [self._row(i, "u1", "private") for i in range(3)]
        with patch.object(secrets_util.Secrets, "list_for_org", return_value=rows), patch.object(
            secrets_util, "is_org_admin"
        ) as is_admin:
            secrets_util.list_secret_metadata(_user(), "org-1")
        is_admin.assert_not_called()

    def test_a_member_cannot_manage_another_members_shared_secret(self):
        rows = [self._row(1, "u2", "organization")]
        with patch.object(secrets_util.Secrets, "list_for_org", return_value=rows), patch.object(
            secrets_util, "is_org_admin", return_value=False
        ):
            items = secrets_util.list_secret_metadata(_user(), "org-1")
        self.assertFalse(items[0]["can_manage"])


class ToolAccessMembershipsTest(unittest.TestCase):
    def test_get_tools_reads_memberships_once_for_restricted_tools(self):
        restricted = {"read": {"group_ids": ["g1"]}}
        catalog = []
        modules = {}
        for i in range(5):
            spec = {
                "name": f"run_{i}",
                "parameters": {"type": "object", "properties": {}},
            }
            catalog.append(
                SimpleNamespace(
                    id=f"t{i}",
                    user_id="owner",
                    access_control=restricted,
                    specs=[spec],
                    meta=None,
                    valves=None,
                )
            )
            modules[f"t{i}"] = SimpleNamespace(**{f"run_{i}": lambda: None})
        request = SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(TOOLS=modules)),
            state=SimpleNamespace(),
            headers={},
        )
        with patch.object(
            access_control.Groups,
            "get_groups_by_member_id",
            return_value=[SimpleNamespace(id="g1")],
        ) as groups, patch(
            "open_webui.models.organizations.Organizations.user_organization_ids",
            return_value=["org-1"],
        ) as orgs:
            tools = tools_util.get_tools(
                request,
                [tool.id for tool in catalog],
                _user(),
                {"__user__": {"id": "u1"}},
                catalog=catalog,
                skill_records=[],
            )

        self.assertEqual(len(tools), 5)
        groups.assert_called_once()
        orgs.assert_called_once()

    def test_has_access_without_memberships_still_reads_them(self):
        with patch.object(
            access_control.Groups, "get_groups_by_member_id", return_value=[]
        ), patch(
            "open_webui.models.organizations.Organizations.user_organization_ids",
            return_value=["org-1"],
        ):
            self.assertTrue(
                access_control.has_access(
                    "u1", "read", {"read": {"organization_ids": ["org-1"]}}
                )
            )


if __name__ == "__main__":
    unittest.main()
