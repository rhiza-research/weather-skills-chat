#!/usr/bin/env bash
# Start a local stack built from this checkout, beside any others, with staging's
# settings, models, skill packs, and sample chats. ./run-compose.sh --name runs it
# with Docker Compose; this script adds the staging data. See wiki/Development.md.
#
#   scripts/preview.sh up [NAME] [run-compose options]   e.g. --isolation=emulator --testing
#   scripts/preview.sh down [NAME]                       remove the stack, its data and image
#   scripts/preview.sh ls                                list running stacks
#
# NAME defaults to the current branch. Needs gcloud signed in and Tailscale up.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

cmd="${1:-}"
shift || true
name="$(git rev-parse --abbrev-ref HEAD)"
if [[ ${1:-} && $1 != --* ]]; then
    name="$1"
    shift
fi
stack="wsc-$(echo "$name" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9\n' '-')"

case "$cmd" in
    ls)
        docker ps --filter "name=^wsc-" --format '{{.Names}}\t{{.Ports}}\t{{.Status}}'
        exit
        ;;
    down)
        exec ./run-compose.sh -q --drop --name="$name"
        ;;
    up) ;;
    *)
        sed -n 2,11p "$0"
        exit 1
        ;;
esac

# One .env for every stack: this checkout's, or the main checkout's in a worktree.
env_file="$ROOT/.env"
[[ -f $env_file ]] || env_file="$(git rev-parse --path-format=absolute --git-common-dir)/../.env"
if [[ ! -f $env_file ]]; then
    echo "Creating $env_file"
    sed "s/^WEBUI_SECRET_KEY=.*/WEBUI_SECRET_KEY=$(openssl rand -hex 32)/" .env.example >"$env_file"
fi

STAGING_API_KEY="$(gcloud secrets versions access latest --project sheerwater \
    --secret weather-skills-chat-staging-api-key)"
export STAGING_API_KEY
CATALOG_MODELS="$(python3 scripts/preview-seed/staging.py catalog)"
SKILL_PACKS="$(python3 scripts/preview-seed/staging.py packs)"
export CATALOG_MODELS SKILL_PACKS
export ENABLE_DEV_LOGIN_BYPASS=true
export BOOTSTRAP_ADMIN_EMAIL=admin@example.com BOOTSTRAP_ADMIN_PASSWORD=preview BOOTSTRAP_ADMIN_NAME=Admin

new=true
docker volume inspect "$stack-data" >/dev/null 2>&1 && new=false

./run-compose.sh -q --build --name="$name" "$@"

port="$(docker port "$stack" 8080 | head -1 | sed 's/.*://')"
url="http://localhost:$port"
echo "Waiting for $url (the first start installs the skill packs) ..."
for _ in $(seq 1 300); do
    curl -fsS "$url/health" >/dev/null 2>&1 && break
    sleep 1
done
curl -fsS "$url/health" >/dev/null || { echo "Not up. Logs: docker logs $stack" >&2; exit 1; }

if [[ $new == true ]]; then
    docker exec -i -w /app/backend "$stack" python - <scripts/preview-seed/seed.py 2>&1 | tail -1
    python3 scripts/preview-seed/staging.py import "$url"
fi
echo "$url"
