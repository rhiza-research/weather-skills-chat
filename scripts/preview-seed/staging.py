"""Copies settings, models, skill packs, and sample chats from staging to a local stack.

Used by scripts/preview.sh; see wiki/Development.md. STAGING_API_KEY is an API key of
staging's platform admin.

    staging.py catalog            CATALOG_MODELS JSON: staging's platform models
    staging.py packs              SKILL_PACKS JSON: staging's platform skill packs
    staging.py import LOCAL_URL CONTAINER
                                  saved settings, then chats tagged preview-seed with their files
"""

import json
import os
import subprocess
import sys
import urllib.request

STAGING = "https://chat-staging.hornbill-avior.ts.net"
SEED_TAG = "preview-seed"
# Staging settings a local stack must not use: its webhook would post local events.
DROP_SETTINGS = ("webhook_url",)
PLATFORM = {"X-Organization-Id": "platform"}
# Unpacks a tar archive from stdin into a chat's sandbox, run in the stack's container.
# The archive upload API would strip weather-skills provenance from the files, as it
# does for code output, so the copies are written straight to disk instead.
EXTRACT = """
import sys, tarfile
from open_webui.utils.artifacts import chat_sandbox, own_sandbox_tree
root = chat_sandbox(sys.argv[1])
with tarfile.open(fileobj=sys.stdin.buffer, mode="r|*") as tar:
    tar.extractall(root, filter="data")
own_sandbox_tree(root)
"""


def call(base, path, token, body=None, raw=False, headers=None):
    request = urllib.request.Request(base + path, method="POST" if body is not None else "GET")
    request.add_header("Authorization", f"Bearer {token}")
    for name, value in (headers or {}).items():
        request.add_header(name, value)
    if isinstance(body, (dict, list)):
        body = json.dumps(body).encode()
        request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, data=body, timeout=120) as response:
        data = response.read()
    return data if raw else json.loads(data)


def staging(path, body=None, raw=False):
    # Platform models and packs are listed in the platform organization.
    return call(STAGING, path, os.environ["STAGING_API_KEY"], body, raw, PLATFORM)


def catalog():
    models = [m for m in staging("/api/v1/models/") if m.get("organization_id") == "platform"]
    for m in models:
        # Large inline images do not fit an environment variable.
        (m.get("meta") or {}).pop("profile_image_url", None)
    keep = ("id", "name", "base_model_id", "meta", "params", "is_active")
    return [{k: m[k] for k in keep if k in m} for m in models]


def packs():
    seen = {}
    for p in staging("/api/v1/skills/"):
        if p.get("organization_id") == "platform":
            seen[(p["git_url"], p["git_ref"])] = {
                "git_url": p["git_url"],
                "ref": p["git_ref"],
                "enabled_by_default": p.get("enabled_by_default", True),
            }
    return list(seen.values())


def import_into(local, container):
    admin = {"email": os.environ["BOOTSTRAP_ADMIN_EMAIL"], "password": os.environ["BOOTSTRAP_ADMIN_PASSWORD"]}
    token = call(local, "/api/v1/auths/signin", "", admin)["token"]

    settings = staging("/api/v1/configs/export")
    for key in DROP_SETTINGS:
        settings.pop(key, None)
    # Admin settings are changed in the platform organization; chats go to the admin's own.
    call(local, "/api/v1/configs/import", token, {"config": settings}, headers=PLATFORM)

    chats = staging("/api/v1/chats/tags", {"name": SEED_TAG, "skip": 0, "limit": 50})
    for listed in chats:
        source = staging(f"/api/v1/chats/{listed['id']}")
        copy = call(
            local,
            "/api/v1/chats/import",
            token,
            {"chat": source["chat"], "meta": source.get("meta") or {}, "pinned": False},
        )
        top = staging(f"/api/v1/chats/{listed['id']}/artifacts?depth=1&provenance=false")
        if top:
            query = "&".join(f"path={urllib.request.quote(e['path'])}" for e in top)
            archive = staging(f"/api/v1/chats/{listed['id']}/artifacts/archive?{query}", raw=True)
            subprocess.run(
                ["docker", "exec", "-i", "-w", "/app/backend", container, "python", "-c", EXTRACT, copy["id"]],
                input=archive,
                stdout=subprocess.DEVNULL,  # the app prints paths on import
                check=True,
            )
        print(f"Copied chat: {listed['title']} ({len(top)} top-level files)")
    print(f"Copied staging settings and {len(chats)} chats tagged {SEED_TAG}")


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "catalog":
        print(json.dumps(catalog()))
    elif command == "packs":
        print(json.dumps(packs()))
    elif command == "import" and len(sys.argv) == 4:
        import_into(sys.argv[2].rstrip("/"), sys.argv[3])
    else:
        sys.exit(__doc__)
