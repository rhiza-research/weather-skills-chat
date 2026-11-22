#!/usr/bin/env bash
# Start a local stack built from this checkout, beside any others, with staging's
# settings, models, skill packs, and sample chats. ./run-compose.sh --name runs it
# with Docker Compose; this script adds the staging data. See wiki/Development.md.
#
#   scripts/preview.sh up [NAME] [--idle=MINUTES] [run-compose options]   e.g. --testing, --isolation=off
#   scripts/preview.sh down [NAME]                       remove the stack, its data and image
#   scripts/preview.sh ls                                list running stacks
#
# NAME defaults to the current branch. up needs gcloud signed in and Tailscale up.
# A stack is removed once it has served no request for --idle minutes (default 60; 0 keeps it).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
main_checkout="$(git rev-parse --path-format=absolute --git-common-dir)/.."

cmd="${1:-}"
shift || true
name="$(git rev-parse --abbrev-ref HEAD)"
if [[ ${1:-} && $1 != -* ]]; then
    name="$1"
    shift
fi
stack="wsc-$(echo "$name" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9\n' '-')"

# Test accounts. The stack creates the admin; seed.py adds the others with the same password.
admin_email=admin@example.com
password=preview
accounts="admin@example.com (platform admin), researcher@example.com (user), pending@example.com (waiting for access)"

stack_url() {
    local port
    port="$(docker port "$stack" 8080 2>/dev/null | head -1 | sed 's/.*://')"
    [[ -n $port ]] && echo "http://localhost:$port"
}

sign_in_help() {
    cat <<EOF
$1
Accounts, all with the password $password: $accounts
Sign in a browser tool:  open $1, then run in the page
  localStorage.removeItem('activeOrganizationId');localStorage.token=(await(await fetch('/api/v1/auths/signin',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({email:'$admin_email',password:'$password'})})).json()).token;location.href='/'
Sign in by hand:         $1/auth?email=$admin_email with the password $password
EOF
}

case "$cmd" in
    ls)
        docker ps --filter "name=^wsc-" --format '{{.Names}}\t{{.Ports}}\t{{.Status}}'
        exit
        ;;
    down)
        exec ./run-compose.sh -q --drop --name="$name"
        ;;
    watch)
        # Internal: up leaves this running to remove the stack once it is idle for $1 minutes.
        # It uses docker alone, so it still works after its worktree is deleted.
        idle="$1"
        cd /
        while sleep 60; do
            docker inspect "$stack" >/dev/null 2>&1 || exit 0
            ((SECONDS < idle * 60)) && continue
            # No grep -q: it would end docker logs early and fail the pipe on a busy stack.
            docker logs --since "${idle}m" "$stack" 2>&1 | grep ' HTTP/[0-9.]*" ' >/dev/null && continue
            docker compose -p "$stack" down --remove-orphans --volumes
            docker image rm "weather-skills-chat:$stack" || true
            exit
        done
        ;;
    up) ;;
    *)
        sed -n 2,11p "$0"
        exit 1
        ;;
esac

idle=60
for arg in "$@"; do
    shift
    if [[ $arg == --idle=* ]]; then idle="${arg#--idle=}"; else set -- "$@" "$arg"; fi
done
[[ $idle =~ ^[0-9]+$ ]] || { echo "--idle takes whole minutes, 0 to keep the stack" >&2; exit 1; }
# The watcher of an earlier up must not remove the stack while it rebuilds.
pkill -f -- "preview.sh watch $name " || true

# One .env for every stack: this checkout's, or the main checkout's in a worktree.
env_file="$ROOT/.env"
[[ -f $env_file ]] || env_file="$main_checkout/.env"
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
export BOOTSTRAP_ADMIN_EMAIL="$admin_email" BOOTSTRAP_ADMIN_PASSWORD="$password" BOOTSTRAP_ADMIN_NAME=Admin

new=true
docker volume inspect "$stack-data" >/dev/null 2>&1 && new=false

# Skills run on the emulated Kubernetes runners, as on staging, unless another isolation is given.
isolation=(--isolation=emulator)
[[ " $* " == *" --isolation"* ]] && isolation=()
./run-compose.sh -q --build --name="$name" "${isolation[@]}" "$@"

url="$(stack_url)"
echo "Waiting for $url (the first start installs the skill packs) ..."
for _ in $(seq 1 300); do
    curl -fsS "$url/health" >/dev/null 2>&1 && break
    sleep 1
done
curl -fsS "$url/health" >/dev/null || { echo "Not up. Logs: docker logs $stack" >&2; exit 1; }

if [[ $new == true ]]; then
    docker exec -i -w /app/backend "$stack" python - <scripts/preview-seed/seed.py 2>&1 | tail -1
    python3 scripts/preview-seed/staging.py import "$url" "$stack"
fi
sign_in_help "$url"
if ((idle > 0)); then
    nohup "$ROOT/scripts/preview.sh" watch "$name" "$idle" >/dev/null 2>&1 &
    echo "Removed, with its data, after $idle minutes without a request. --idle=MINUTES changes that; --idle=0 keeps it."
fi
