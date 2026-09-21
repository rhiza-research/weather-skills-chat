from test.util.abstract_integration_test import AbstractPostgresTest
from test.util.mock_user import mock_webui_user


MODEL_PAYLOAD = {
    "id": "catalog-wrapper",
    "base_model_id": "openai/gpt-4o",
    "name": "Catalog Wrapper",
    "meta": {
        "profile_image_url": "/static/favicon.png",
        "description": "desc",
        "capabilities": None,
        "model_config": {},
    },
    "params": {},
}


class TestCatalogAccess(AbstractPostgresTest):
    BASE_PATH = "/api/v1"

    def setup_method(self):
        super().setup_method()
        from open_webui.models.organizations import Organizations
        from open_webui.models.users import Users

        self.users = Users
        self.orgs = Organizations
        self.users.insert_new_user(
            id="admin",
            name="admin",
            email="admin@openwebui.com",
            profile_image_url="/admin.png",
            role="admin",
        )
        self.users.insert_new_user(
            id="owner",
            name="owner",
            email="owner@openwebui.com",
            profile_image_url="/owner.png",
            role="user",
        )
        self.users.insert_new_user(
            id="outsider",
            name="outsider",
            email="outsider@openwebui.com",
            profile_image_url="/outsider.png",
            role="user",
        )
        self.orgs.ensure_platform("admin")

    def test_public_model_override_and_can_add(self):
        with mock_webui_user(id="admin", role="admin"):
            created = self.fast_api_client.post(
                self.create_url("/models/create"),
                json={**MODEL_PAYLOAD, "enabled_by_default": True},
                headers={"X-Organization-Id": "platform"},
            )
        assert created.status_code == 200, created.text
        assert created.json()["visibility"] == "public"

        with mock_webui_user(id="owner"):
            listed = self.fast_api_client.get(
                self.create_url("/models/"),
                headers={"X-Organization-Id": "owner"},
            )
        assert listed.status_code == 200
        ids = {m["id"] for m in listed.json()}
        assert "catalog-wrapper" in ids
        item = next(m for m in listed.json() if m["id"] == "catalog-wrapper")
        assert item["enabled"] is True

        with mock_webui_user(id="owner"):
            toggled = self.fast_api_client.post(
                self.create_url("/models/model/enabled?id=catalog-wrapper"),
                json={"enabled": False},
                headers={"X-Organization-Id": "owner"},
            )
        assert toggled.status_code == 200
        assert toggled.json()["enabled"] is False

        with mock_webui_user(id="owner"):
            listed = self.fast_api_client.get(
                self.create_url("/models/"),
                headers={"X-Organization-Id": "owner"},
            )
        assert listed.status_code == 200
        item = next(m for m in listed.json() if m["id"] == "catalog-wrapper")
        assert item["enabled"] is False

        with mock_webui_user(id="owner"):
            picker = self.fast_api_client.get(
                "/api/models",
                headers={"X-Organization-Id": "owner"},
            )
        assert picker.status_code == 200
        assert "catalog-wrapper" not in {
            m["id"] for m in picker.json().get("data", [])
        }

        with mock_webui_user(id="outsider"):
            listed = self.fast_api_client.get(
                self.create_url("/models/"),
                headers={"X-Organization-Id": "outsider"},
            )
        assert "catalog-wrapper" in {m["id"] for m in listed.json()}
        item = next(m for m in listed.json() if m["id"] == "catalog-wrapper")
        assert item["enabled"] is True

        private_payload = {**MODEL_PAYLOAD, "id": "org-private", "name": "Org Private"}
        with mock_webui_user(id="owner"):
            rejected = self.fast_api_client.post(
                self.create_url("/models/create"),
                json=private_payload,
                headers={"X-Organization-Id": "owner"},
            )
        assert rejected.status_code in (401, 403)

        with mock_webui_user(id="admin", role="admin"):
            flags = self.fast_api_client.post(
                self.create_url("/organizations/owner/update"),
                json={"can_add_models": True},
            )
        assert flags.status_code == 200
        assert flags.json()["can_add_models"] is True

        with mock_webui_user(id="owner"):
            private = self.fast_api_client.post(
                self.create_url("/models/create"),
                json=private_payload,
                headers={"X-Organization-Id": "owner"},
            )
        assert private.status_code == 200, private.text
        assert private.json()["visibility"] == "organization"
        assert private.json()["organization_id"] == "owner"

        with mock_webui_user(id="outsider"):
            listed = self.fast_api_client.get(
                self.create_url("/models/"),
                headers={"X-Organization-Id": "outsider"},
            )
        assert "org-private" not in {m["id"] for m in listed.json()}

        with mock_webui_user(id="owner"):
            listed = self.fast_api_client.get(
                self.create_url("/models/"),
                headers={"X-Organization-Id": "owner"},
            )
        assert "org-private" in {m["id"] for m in listed.json()}

    def test_chat_picker_excludes_raw_connection_ids(self):
        with mock_webui_user(id="admin", role="admin"):
            created = self.fast_api_client.post(
                self.create_url("/models/create"),
                json=MODEL_PAYLOAD,
                headers={"X-Organization-Id": "platform"},
            )
        assert created.status_code == 200

        with mock_webui_user(id="owner"):
            response = self.fast_api_client.get(
                "/api/models",
                headers={"X-Organization-Id": "owner"},
            )
        assert response.status_code == 200
        ids = [m["id"] for m in response.json().get("data", [])]
        assert "openai/gpt-4o" not in ids
        assert "catalog-wrapper" in ids
