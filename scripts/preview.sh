#!/usr/bin/env bash
# Start a local stack built from this checkout, beside any others, with staging's
# settings, models, skill packs, and sample chats. ./run-compose.sh --name runs it
# with Docker Compose; this script adds the staging data. See wiki/Development.md.
#
#   scripts/preview.sh up [NAME] [run-compose options]   e.g. --testing, --isolation=off
#   scripts/preview.sh shot [NAME] [PAGE] [--as EMAIL] [--out FILE.png] [--size WxH]
#                                                        sign in and save a screenshot of PAGE (default /)
#   scripts/preview.sh down [NAME]                       remove the stack, its data and image
#   scripts/preview.sh ls                                list running stacks
#
# NAME defaults to the current branch. up needs gcloud signed in and Tailscale up.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
main_checkout="$(git rev-parse --path-format=absolute --git-common-dir)/.."

cmd="${1:-}"
shift || true
name="$(git rev-parse --abbrev-ref HEAD)"
if [[ ${1:-} && $1 != -* && $1 != /* ]]; then
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
Screenshot, signed in:   scripts/preview.sh shot $name [PAGE] [--as EMAIL] [--out FILE.png]
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
    shot)
        url="$(stack_url)" || { echo "$stack is not running: scripts/preview.sh up $name" >&2; exit 1; }
        page=/ email="$admin_email" size=1280x800
        out="${TMPDIR:-/tmp}/$stack-$(date +%Y%m%d-%H%M%S).png"
        while [[ $# -gt 0 ]]; do
            case "$1" in
                --as) email="$2"; shift ;;
                --out) out="$2"; shift ;;
                --size) size="$2"; shift ;;
                /*) page="$1" ;;
                *) sed -n 2,12p "$0"; exit 1 ;;
            esac
            shift
        done
        # Playwright from the browser tests; a worktree uses the main checkout's.
        modules="$ROOT/node_modules"
        [[ -d $modules/playwright ]] || modules="$main_checkout/node_modules"
        NODE_PATH="$modules" exec node scripts/preview-seed/shot.cjs "$url" "$page" "$out" "$email" "$password" "$size"
        ;;
    up) ;;
    *)
        sed -n 2,12p "$0"
        exit 1
        ;;
esac

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
    python3 scripts/preview-seed/staging.py import "$url"
fi
sign_in_help "$url"
