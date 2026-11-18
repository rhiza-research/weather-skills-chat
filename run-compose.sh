#!/bin/bash

# Define color and formatting codes
BOLD='\033[1m'
GREEN='\033[1;32m'
WHITE='\033[1;37m'
RED='\033[0;31m'
NC='\033[0m' # No Color
# Unicode character for tick mark
TICK='\u2713'

# Detect GPU driver
get_gpu_driver() {
    # Detect NVIDIA GPUs using lspci or nvidia-smi
    if lspci | grep -i nvidia >/dev/null || nvidia-smi >/dev/null 2>&1; then
        echo "nvidia"
        return
    fi

    # Detect AMD GPUs (including GCN architecture check for amdgpu vs radeon)
    if lspci | grep -i amd >/dev/null; then
        # List of known GCN and later architecture cards
        # This is a simplified list, and in a real-world scenario, you'd want a more comprehensive one
        local gcn_and_later=("Radeon HD 7000" "Radeon HD 8000" "Radeon R5" "Radeon R7" "Radeon R9" "Radeon RX")

        # Get GPU information
        local gpu_info=$(lspci | grep -i 'vga.*amd')

        for model in "${gcn_and_later[@]}"; do
            if echo "$gpu_info" | grep -iq "$model"; then
                echo "amdgpu"
                return
            fi
        done

        # Default to radeon if no GCN or later architecture is detected
        echo "radeon"
        return
    fi

    # Detect Intel GPUs
    if lspci | grep -i intel >/dev/null; then
        echo "i915"
        return
    fi

    # If no known GPU is detected
    echo "Unknown or unsupported GPU driver"
    exit 1
}

# Function for rolling animation
show_loading() {
    local spin='-\|/'
    local i=0

    printf " "

    while kill -0 $1 2>/dev/null; do
        i=$(( (i+1) %4 ))
        printf "\b${spin:$i:1}"
        sleep .1
    done

    # Replace the spinner with a tick
    printf "\b${GREEN}${TICK}${NC}"
}

# Usage information
usage() {
    echo "Usage: $0 [OPTIONS]"
    echo "Options:"
    echo "  --testing                  Start Caddy so the browser uses HTTP/2 on CADDY_HTTPS_PORT (3443)."
    echo "  --isolation=MODE           Skill isolation: off, landlock, or emulator (default: off)."
    echo "  --ollama                   Run an Ollama container and connect the web UI to it."
    echo "  --enable-gpu[count=COUNT]  Enable GPU support with the specified count (requires --ollama)."
    echo "  --enable-api[port=PORT]    Enable API and expose it on the specified port (requires --ollama)."
    echo "  --webui[port=PORT]         Set the port for the web user interface."
    echo "  --data[folder=PATH]        Bind mount for ollama data folder (by default will create the 'ollama' volume; requires --ollama)."
    echo "  --playwright               Enable Playwright support for web scraping."
    echo "  --build                    Build the docker image before running the compose project."
    echo "  --drop                     Drop the compose project."
    echo "  --name=NAME                Run a separate stack named NAME with its own containers, data, and free ports."
    echo "                             With --drop, also remove its data and image."
    echo "  -q, --quiet                Run script in headless mode."
    echo "  -h, --help                 Show this help message."
    echo ""
    echo "Examples:"
    echo "  $0 --drop"
    echo "  $0 --testing --isolation=off"
    echo "  $0 --testing --isolation=emulator"
    echo "  $0 --testing --isolation=emulator --build"
    echo "  $0 --ollama"
    echo "  $0 --ollama --enable-gpu[count=1]"
    echo "  $0 --ollama --enable-gpu[count=all]"
    echo "  $0 --ollama --enable-api[port=11435]"
    echo "  $0 --ollama --enable-gpu[count=1] --enable-api[port=12345] --webui[port=3000]"
    echo "  $0 --ollama --enable-gpu[count=1] --enable-api[port=12345] --webui[port=3000] --data[folder=./ollama-data]"
    echo "  $0 --ollama --enable-gpu[count=1] --enable-api[port=12345] --webui[port=3000] --data[folder=./ollama-data] --build"
    echo ""
    echo "This script configures and runs a docker-compose setup with optional GPU support, API exposure, and web UI configuration."
    echo "Every start passes --force-recreate."
    echo ""
    echo "About the gpu to use, the script automatically detects it using the "lspci" command."
    echo "In this case the gpu detected is: $(get_gpu_driver)"
}

ROOT="$(cd "$(dirname "$0")" && pwd)"
# A git worktree has no .env of its own; it uses the main checkout's.
env_file="$ROOT/.env"
[[ -f $env_file ]] || env_file="$(git -C "$ROOT" rev-parse --path-format=absolute --git-common-dir)/../.env"
if [[ -f $env_file ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$env_file"
    set +a
fi
# Run mode belongs on the command line, not in .env.
unset COMPOSE_MODE COMPOSE_PROFILES \
    SKILL_SANDLOCK SKILL_SANDBOX_BACKEND \
    SKILL_K8S_SANDBOX_ENABLED SKILL_K8S_EMULATOR \
    SKILL_K8S_BIND_TOKEN SKILL_K8S_APISERVER
cd "$ROOT"

# Default values
gpu_count=1
api_port=11435
# Empty unless --webui[port=PORT] is given, so OPEN_WEBUI_PORT from .env applies.
webui_port=
headless=false
build_image=false
kill_compose=false
enable_playwright=false
enable_testing=false
isolation=off
enable_ollama=false
enable_gpu=false
enable_api=false
data_dir=
stack_name=

# Function to extract value from the parameter
# A bash regex, because macOS sed does not accept the GNU "t; s/.*//" form.
extract_value() {
    if [[ $1 =~ \[[^=]*=([^]]*)\] ]]; then
        echo "${BASH_REMATCH[1]}"
    fi
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    key="$1"

    case $key in
        --ollama)
            enable_ollama=true
            ;;
        --enable-gpu*)
            enable_gpu=true
            value=$(extract_value "$key")
            gpu_count=${value:-1}
            ;;
        --enable-api*)
            enable_api=true
            value=$(extract_value "$key")
            api_port=${value:-11435}
            ;;
        --webui*)
            value=$(extract_value "$key")
            webui_port=$value
            ;;
        --data*)
            value=$(extract_value "$key")
            data_dir=${value:-"./ollama-data"}
            ;;
        --playwright)
            enable_playwright=true
            ;;
        --testing)
            enable_testing=true
            ;;
        --isolation=*)
            isolation="${key#--isolation=}"
            ;;
        --isolation)
            shift
            isolation="${1:-}"
            if [[ -z $isolation ]]; then
                echo -e "${RED}${BOLD}--isolation needs off, landlock, or emulator.${NC}" >&2
                exit 1
            fi
            ;;
        --isolation*)
            isolation=$(extract_value "$key")
            isolation=${isolation:-off}
            ;;
        --name=*)
            stack_name="$(echo "${key#--name=}" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9\n' '-')"
            ;;
        --drop)
            kill_compose=true
            ;;
        --build)
            build_image=true
            ;;
        -q|--quiet)
            headless=true
            ;;
        -h|--help)
            usage
            exit
            ;;
        *)
            # Unknown option
            echo "Unknown option: $key"
            usage
            exit 1
            ;;
    esac
    shift # past argument or value
done

if [[ $enable_ollama != true ]]; then
    ollama_only=""
    if [[ $enable_gpu == true ]]; then
        ollama_only="--enable-gpu"
    elif [[ $enable_api == true ]]; then
        ollama_only="--enable-api"
    elif [[ -n $data_dir ]]; then
        ollama_only="--data"
    fi
    if [[ -n $ollama_only ]]; then
        echo -e "${RED}${BOLD}$ollama_only requires --ollama.${NC}" >&2
        exit 1
    fi
fi

if [[ -n $stack_name ]]; then
    # A stack beside any other: its own Compose project, containers, image tag,
    # volumes, and ports. A running stack keeps its ports; otherwise each takes
    # the first free port from its base. Another stack starting at the same time
    # can take the same port first; the start below then picks again.
    stack="wsc-$stack_name"
    export COMPOSE_PROJECT_NAME="$stack" WEBUI_CONTAINER_NAME="$stack" \
        CADDY_CONTAINER_NAME="$stack-h2" EMULATOR_CONTAINER_NAME="$stack-emulator" \
        WEBUI_IMAGE=weather-skills-chat WEBUI_DOCKER_TAG="$stack" \
        WEBUI_DATA_VOLUME="$stack-data" CADDY_DATA_VOLUME="$stack-caddy"
    # Only this computer can reach a named stack; it signs in without a password.
    export BIND_ADDRESS=127.0.0.1
    taken=()
    pick_port() { # container, container port, base
        local p
        p="$(docker port "$1" "$2" 2>/dev/null | head -1 | sed 's/.*://' || true)"
        if [[ -z $p ]]; then
            p=$3
            while lsof -nP -iTCP:"$p" -sTCP:LISTEN >/dev/null 2>&1 || [[ " ${taken[*]} " == *" $p "* ]]; do
                p=$((p + 1))
            done
        fi
        echo "$p"
    }
    pick_stack_ports() {
        taken=()
        OPEN_WEBUI_PORT="$(pick_port "$stack" 8080 3100)"
        taken+=("$OPEN_WEBUI_PORT")
        CADDY_HTTPS_PORT="$(pick_port "$stack-h2" 443 4443)"
        taken+=("$CADDY_HTTPS_PORT")
        CADDY_HTTP_PORT="$(pick_port "$stack-h2" 80 8100)"
        export OPEN_WEBUI_PORT CADDY_HTTPS_PORT CADDY_HTTP_PORT
        export WEBUI_URL="http://localhost:$OPEN_WEBUI_PORT"
        if [[ $enable_testing == true ]]; then
            export WEBUI_URL="https://localhost:$CADDY_HTTPS_PORT"
        fi
    }
    pick_stack_ports
fi

compose_profiles=()
if [[ $enable_testing == true ]]; then
    compose_profiles+=(testing)
    if [[ -z ${WEBUI_URL:-} ]]; then
        export WEBUI_URL="https://localhost:${CADDY_HTTPS_PORT:-3443}"
    fi
fi

case "$isolation" in
    off)
        export SKILL_SANDLOCK=false
        export SKILL_SANDBOX_BACKEND=landlock
        export SKILL_K8S_SANDBOX_ENABLED=false
        export SKILL_K8S_EMULATOR=false
        ;;
    landlock)
        export SKILL_SANDLOCK=true
        export SKILL_SANDBOX_BACKEND=landlock
        export SKILL_K8S_SANDBOX_ENABLED=false
        export SKILL_K8S_EMULATOR=false
        ;;
    emulator)
        export SKILL_SANDLOCK=false
        export SKILL_SANDBOX_BACKEND=k8s
        export SKILL_K8S_SANDBOX_ENABLED=true
        export SKILL_K8S_EMULATOR=true
        export SKILL_K8S_BIND_TOKEN=dev
        export SKILL_K8S_APISERVER=http://emulator:18080
        compose_profiles+=(emulator)
        ;;
    *)
        echo -e "${RED}${BOLD}Unknown --isolation=$isolation (use off, landlock, or emulator).${NC}" >&2
        exit 1
        ;;
esac

if [[ ${#compose_profiles[@]} -gt 0 ]]; then
    export COMPOSE_PROFILES
    COMPOSE_PROFILES=$(IFS=,; echo "${compose_profiles[*]}")
fi

profile_args=()
for profile in testing emulator; do
    profile_args+=(--profile "$profile")
done

if [[ $kill_compose == true ]]; then
    if [[ -n $stack_name ]]; then
        # A named stack is throwaway: its data and image go with it.
        docker compose "${profile_args[@]}" down --remove-orphans --volumes
        docker image rm "$WEBUI_IMAGE:$WEBUI_DOCKER_TAG" 2>/dev/null || true
    else
        docker compose "${profile_args[@]}" down --remove-orphans
    fi
    echo -e "${GREEN}${BOLD}Compose project dropped successfully.${NC}"
    exit
else
    DEFAULT_COMPOSE_COMMAND="docker compose"
    for profile in "${compose_profiles[@]}"; do
        DEFAULT_COMPOSE_COMMAND+=" --profile $profile"
    done
    DEFAULT_COMPOSE_COMMAND+=" -f docker-compose.yaml"
    if [[ $enable_ollama == true ]]; then
        DEFAULT_COMPOSE_COMMAND+=" -f docker-compose.ollama.yaml"
    fi
    if [[ $enable_gpu == true ]]; then
        # Validate and process command-line arguments
        if [[ -n $gpu_count ]]; then
            if ! [[ $gpu_count =~ ^([0-9]+|all)$ ]]; then
                echo "Invalid GPU count: $gpu_count"
                exit 1
            fi
            echo "Enabling GPU with $gpu_count GPUs"
            # Add your GPU allocation logic here
            export OLLAMA_GPU_DRIVER=$(get_gpu_driver)
            export OLLAMA_GPU_COUNT=$gpu_count # Set OLLAMA_GPU_COUNT environment variable
        fi
        DEFAULT_COMPOSE_COMMAND+=" -f docker-compose.gpu.yaml"
    fi
    if [[ $enable_api == true ]]; then
        DEFAULT_COMPOSE_COMMAND+=" -f docker-compose.api.yaml"
        if [[ -n $api_port ]]; then
            export OLLAMA_WEBAPI_PORT=$api_port # Set OLLAMA_WEBAPI_PORT environment variable
        fi
    fi
    if [[ -n $data_dir ]]; then
        DEFAULT_COMPOSE_COMMAND+=" -f docker-compose.data.yaml"
        export OLLAMA_DATA_DIR=$data_dir # Set OLLAMA_DATA_DIR environment variable
    fi
    if [[ $enable_playwright == true ]]; then
        DEFAULT_COMPOSE_COMMAND+=" -f docker-compose.playwright.yaml"
    fi
    if [[ -n $webui_port ]]; then
        export OPEN_WEBUI_PORT=$webui_port # Set OPEN_WEBUI_PORT environment variable
    fi
    DEFAULT_COMPOSE_COMMAND+=" up -d"
    DEFAULT_COMPOSE_COMMAND+=" --remove-orphans"
    DEFAULT_COMPOSE_COMMAND+=" --force-recreate"
    if [[ $build_image == true ]]; then
        DEFAULT_COMPOSE_COMMAND+=" --build"
    fi
fi

# Recap of environment variables
echo
echo -e "${WHITE}${BOLD}Current Setup:${NC}"
echo -e "   ${GREEN}${BOLD}Ollama:${NC} $enable_ollama"
echo -e "   ${GREEN}${BOLD}GPU Driver:${NC} ${OLLAMA_GPU_DRIVER:-Not Enabled}"
echo -e "   ${GREEN}${BOLD}GPU Count:${NC} ${OLLAMA_GPU_COUNT:-Not Enabled}"
echo -e "   ${GREEN}${BOLD}WebAPI Port:${NC} ${OLLAMA_WEBAPI_PORT:-Not Enabled}"
echo -e "   ${GREEN}${BOLD}Data Folder:${NC} ${data_dir:-Using ollama volume}"
echo -e "   ${GREEN}${BOLD}WebUI Port:${NC} ${OPEN_WEBUI_PORT:-OPEN_WEBUI_PORT from .env, or 3000}"
echo -e "   ${GREEN}${BOLD}Playwright:${NC} ${enable_playwright:-false}"
echo -e "   ${GREEN}${BOLD}Testing (HTTP/2):${NC} $enable_testing"
echo -e "   ${GREEN}${BOLD}Isolation:${NC} $isolation"
echo -e "   ${GREEN}${BOLD}Profiles:${NC} ${COMPOSE_PROFILES:-none}"
echo

if [[ $headless == true ]]; then
    echo -ne "${WHITE}${BOLD}Running in headless mode... ${NC}"
    choice="y"
else
    # Ask for user acceptance
    echo -ne "${WHITE}${BOLD}Do you want to proceed with current setup? (Y/n): ${NC}"
    read -n1 -s choice
fi

echo

if [[ $choice == "" || $choice == "y" ]]; then
    errors="$(mktemp)"
    for attempt in 1 2 3 4 5; do
        eval "$DEFAULT_COMPOSE_COMMAND" 2> >(tee "$errors" >&2)
        status=$?
        wait # for tee to finish writing $errors
        # A named stack whose port another stack took first picks free ports again.
        if [[ $status -ne 0 && -n $stack_name && -z $webui_port ]] &&
            grep -qiE "port is already allocated|address already in use" "$errors"; then
            echo -e "${WHITE}${BOLD}A port was taken; picking free ports again (attempt $attempt of 5).${NC}"
            pick_stack_ports
            continue
        fi
        break
    done
    rm -f "$errors"

    echo
    if [[ $status -eq 0 ]]; then
        echo -e "${GREEN}${BOLD}Compose project started successfully.${NC}"
    else
        echo -e "${RED}${BOLD}There was an error starting the compose project.${NC}"
        exit "$status"
    fi
else
    echo "Aborted."
fi

echo
