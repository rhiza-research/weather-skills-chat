from test.util.abstract_integration_test import AbstractPostgresTest
from test.util.mock_user import mock_webui_user


class TestOrganizations(AbstractPostgresTest):
    BASE_PATH = "/api/v1/organizations"

    def setup_method(self):
        super().setup_method()
        from open_webui.models.chats import Chats
        from open_webui.models.organizations import Organizations
        from open_webui.models.users import Users

        self.users = Users
        self.orgs = Organizations
        self.chats = Chats
        self.users.insert_new_user(
            id="owner",
            name="owner",
            email="owner@openwebui.com",
            profile_image_url="/owner.png",
            role="user",
        )
        self.users.insert_new_user(
            id="member",
            name="member",
            email="member@openwebui.com",
            profile_image_url="/member.png",
            role="user",
        )
        self.users.insert_new_user(
            id="outsider",
            name="outsider",
            email="outsider@openwebui.com",
            profile_image_url="/outsider.png",
            role="user",
        )

    def test_personal_org_and_workspace_crud(self):
        with mock_webui_user(id="owner"):
            response = self.fast_api_client.get(self.create_url("/"))
        assert response.status_code == 200
        ids = {org["id"] for org in response.json()}
        assert "owner" in ids
        personal = next(org for org in response.json() if org["id"] == "owner")
        assert personal["kind"] == "personal"
        assert personal["monthly_limit_usd"] == 300

        with mock_webui_user(id="owner"):
            response = self.fast_api_client.post(
                self.create_url("/"),
                json={"name": "Workspace A", "description": "desc"},
            )
        assert response.status_code == 200
        workspace = response.json()
        assert workspace["kind"] == "workspace"
        assert workspace["role"] == "owner"
        assert workspace["active"] is False
        assert workspace["monthly_limit_usd"] == 300
        workspace_id = workspace["id"]

        with mock_webui_user(id="owner"):
            listed = self.fast_api_client.get(self.create_url("/"))
        assert workspace_id not in {org["id"] for org in listed.json()}

        with mock_webui_user(id="member"):
            forbidden = self.fast_api_client.post(
                self.create_url(f"/{workspace_id}/activate")
            )
        assert forbidden.status_code == 403

        self.orgs.ensure_platform("owner")
        with mock_webui_user(id="owner"):
            response = self.fast_api_client.post(
                self.create_url(f"/{workspace_id}/activate")
            )
        assert response.status_code == 200
        assert response.json()["active"] is True

        with mock_webui_user(id="owner"):
            listed = self.fast_api_client.get(self.create_url("/"))
        assert workspace_id in {org["id"] for org in listed.json()}

        with mock_webui_user(id="owner"):
            response = self.fast_api_client.post(
                self.create_url(f"/{workspace_id}/members"),
                json={"user_id": "member", "role": "user"},
            )
        assert response.status_code == 200
        roles = {m["user_id"]: m["role"] for m in response.json()["members"]}
        assert roles["member"] == "user"

        with mock_webui_user(id="owner"):
            response = self.fast_api_client.post(
                self.create_url(f"/{workspace_id}/members/member"),
                json={"role": "admin"},
            )
        assert response.status_code == 200

        with mock_webui_user(id="outsider"):
            response = self.fast_api_client.get(self.create_url(f"/{workspace_id}"))
        assert response.status_code == 403

        with mock_webui_user(id="owner"):
            response = self.fast_api_client.post(
                self.create_url("/owner/members"),
                json={"user_id": "member", "role": "user"},
            )
        assert response.status_code == 400

    def test_update_and_delete_workspace(self):
        with mock_webui_user(id="owner"):
            created = self.fast_api_client.post(
                self.create_url("/"),
                json={"name": "Temp Org"},
            ).json()
        workspace_id = created["id"]
        self.orgs.ensure_platform("owner")
        with mock_webui_user(id="owner"):
            self.fast_api_client.post(self.create_url(f"/{workspace_id}/activate"))

        with mock_webui_user(id="outsider"):
            denied = self.fast_api_client.post(
                self.create_url(f"/{workspace_id}/update"),
                json={"name": "Hijacked"},
            )
        assert denied.status_code == 403

        with mock_webui_user(id="owner"):
            updated = self.fast_api_client.post(
                self.create_url(f"/{workspace_id}/update"),
                json={"name": "Renamed Org", "description": "updated"},
            )
        assert updated.status_code == 200
        assert updated.json()["name"] == "Renamed Org"

        with mock_webui_user(id="owner"):
            personal = self.fast_api_client.delete(self.create_url("/owner"))
        assert personal.status_code == 400

        with mock_webui_user(id="outsider"):
            denied_delete = self.fast_api_client.delete(
                self.create_url(f"/{workspace_id}")
            )
        assert denied_delete.status_code == 403

        with mock_webui_user(id="owner"):
            deleted = self.fast_api_client.delete(self.create_url(f"/{workspace_id}"))
        assert deleted.status_code == 200

        with mock_webui_user(id="owner"):
            missing = self.fast_api_client.get(self.create_url(f"/{workspace_id}"))
        assert missing.status_code == 404

    def test_context_isolation_and_private_chats(self):

        with mock_webui_user(id="owner"):
            created = self.fast_api_client.post(
                self.create_url("/"),
                json={"name": "Workspace B"},
            ).json()
        workspace_id = created["id"]
        self.orgs.ensure_platform("owner")
        with mock_webui_user(id="owner"):
            self.fast_api_client.post(self.create_url(f"/{workspace_id}/activate"))
        with mock_webui_user(id="owner"):
            self.fast_api_client.post(
                self.create_url(f"/{workspace_id}/members"),
                json={"user_id": "member", "role": "user"},
            )

        with mock_webui_user(id="owner"):
            private = self.fast_api_client.post(
                "/api/v1/chats/new",
                headers={"X-Organization-Id": workspace_id},
                json={
                    "chat": {"title": "secret notes"},
                    "organization_id": workspace_id,
                    "visibility": "private",
                },
            )
        assert private.status_code == 200
        private_id = private.json()["id"]
        assert private.json()["visibility"] == "private"

        with mock_webui_user(id="member"):
            listed = self.fast_api_client.get(
                "/api/v1/chats/",
                headers={"X-Organization-Id": workspace_id},
            )
        assert listed.status_code == 200
        assert listed.json() == []

        with mock_webui_user(id="member"):
            forbidden = self.fast_api_client.get(f"/api/v1/chats/{private_id}")
        assert forbidden.status_code in (401, 403, 404)

        with mock_webui_user(id="owner"):
            shared = self.fast_api_client.post(
                f"/api/v1/chats/{private_id}/visibility",
                json={"visibility": "organization"},
            )
        assert shared.status_code == 200
        assert shared.json()["visibility"] == "organization"

        with mock_webui_user(id="member"):
            listed = self.fast_api_client.get(
                "/api/v1/chats/",
                headers={"X-Organization-Id": workspace_id},
            )
        assert any(chat["id"] == private_id for chat in listed.json())

        with mock_webui_user(id="owner"):
            personal_chat = self.fast_api_client.post(
                "/api/v1/chats/new",
                json={"chat": {"title": "personal"}},
            )
        assert personal_chat.status_code == 200
        personal_id = personal_chat.json()["id"]
        with mock_webui_user(id="owner"):
            share = self.fast_api_client.post(f"/api/v1/chats/{personal_id}/share")
        assert share.status_code == 403
        with mock_webui_user(id="owner"):
            vis = self.fast_api_client.post(
                f"/api/v1/chats/{personal_id}/visibility",
                json={"visibility": "organization"},
            )
        assert vis.status_code == 403

        with mock_webui_user(id="member"):
            isolated = self.fast_api_client.get(
                "/api/v1/chats/",
                headers={"X-Organization-Id": "member"},
            )
        assert isolated.status_code == 200
        assert all(chat["id"] != private_id for chat in isolated.json())

    def test_platform_admin_sync_and_user_delete(self):
        from open_webui.models.chats import ChatForm, Chats
        from open_webui.models.organizations import Organizations, PLATFORM_ORG_ID

        Organizations.ensure_platform("owner")
        owner = self.users.get_user_by_id("owner")
        assert owner.role == "user"
        assert Organizations.get_member(PLATFORM_ORG_ID, "owner").role == "owner"

        with mock_webui_user(id="owner"):
            workspace = self.fast_api_client.post(
                self.create_url("/"),
                json={"name": "Keep me"},
            ).json()
        workspace_id = workspace["id"]
        with mock_webui_user(id="owner"):
            self.fast_api_client.post(self.create_url(f"/{workspace_id}/activate"))
        with mock_webui_user(id="owner"):
            self.fast_api_client.post(
                self.create_url(f"/{workspace_id}/members"),
                json={"user_id": "member", "role": "user"},
            )

        shared = Chats.insert_new_chat(
            "member",
            ChatForm(
                chat={"title": "shared work"},
                organization_id=workspace_id,
                visibility="organization",
            ),
        )
        private = Chats.insert_new_chat(
            "member",
            ChatForm(
                chat={"title": "private work"},
                organization_id=workspace_id,
                visibility="private",
            ),
        )
        personal = Chats.insert_new_chat(
            "member",
            ChatForm(chat={"title": "personal work"}),
        )

        assert self.users.delete_user_by_id("member") is True
        assert self.users.get_user_by_id("member") is None
        assert Organizations.get_organization_by_id("member") is None
        assert Chats.get_chat_by_id(personal.id) is None
        assert Chats.get_chat_by_id(private.id) is None
        kept = Chats.get_chat_by_id(shared.id)
        assert kept is not None
        assert kept.visibility == "organization"
        assert kept.user_id == "member"
        assert Organizations.get_member(workspace_id, "member") is None
        assert Organizations.get_member(PLATFORM_ORG_ID, "owner") is not None

    def test_monthly_limit_requires_platform_org_header(self):
        from open_webui.models.organizations import Organizations, PLATFORM_ORG_ID

        Organizations.ensure_platform("owner")
        with mock_webui_user(id="owner"):
            workspace = self.fast_api_client.post(
                self.create_url("/"),
                json={"name": "Capped Org"},
            ).json()
        workspace_id = workspace["id"]

        with mock_webui_user(id="owner"):
            denied = self.fast_api_client.post(
                self.create_url(f"/{workspace_id}/update"),
                headers={"X-Organization-Id": workspace_id},
                json={"monthly_limit_usd": 50},
            )
        assert denied.status_code == 403

        with mock_webui_user(id="outsider"):
            denied_all = self.fast_api_client.get(
                self.create_url("/all"),
                headers={"X-Organization-Id": PLATFORM_ORG_ID},
            )
        assert denied_all.status_code == 403

        with mock_webui_user(id="owner"):
            denied_list = self.fast_api_client.get(
                self.create_url("/all"),
                headers={"X-Organization-Id": workspace_id},
            )
        assert denied_list.status_code == 403

        with mock_webui_user(id="owner"):
            updated = self.fast_api_client.post(
                self.create_url(f"/{workspace_id}/update"),
                headers={"X-Organization-Id": PLATFORM_ORG_ID},
                json={"monthly_limit_usd": 50},
            )
        assert updated.status_code == 200
        assert updated.json()["monthly_limit_usd"] == 50

        with mock_webui_user(id="owner"):
            personal = self.fast_api_client.post(
                self.create_url("/owner/update"),
                headers={"X-Organization-Id": PLATFORM_ORG_ID},
                json={"monthly_limit_usd": 125},
            )
        assert personal.status_code == 200
        assert personal.json()["monthly_limit_usd"] == 125

        with mock_webui_user(id="owner"):
            listed = self.fast_api_client.get(
                self.create_url("/all"),
                headers={"X-Organization-Id": PLATFORM_ORG_ID},
            )
        assert listed.status_code == 200
        capped = next(org for org in listed.json() if org["id"] == workspace_id)
        assert capped["monthly_limit_usd"] == 50
        owner_personal = next(org for org in listed.json() if org["id"] == "owner")
        assert owner_personal["monthly_limit_usd"] == 125
