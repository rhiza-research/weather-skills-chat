# Development

This page covers running Weather Skills Chat from a source checkout. Which branch pull requests target, and how changes reach staging and production, is described under the release model on [[Deployment]].

## Requirements

- Node.js 18.13 through 22.x, and npm.
- Python 3.11 or 3.12, with the packages in `pyproject.toml`. `uv sync` installs them, along with the development group the tests need.
- `git` and `uv` on `PATH`, for [[Skill Packs]].

## Running the app

Start the frontend and the backend in two terminals.

- Frontend: `npm run dev` from the repository root. It starts a development server that sends its API calls to port 8080 on the same host.
- Backend: `./dev.sh` from the `backend` directory. It serves the API on port 8080, or on `PORT` when set, and reloads when code changes.

Without `DATA_DIR`, the backend keeps its data in `backend/data`. In development mode the backend also serves interactive API documentation at `/docs`.

Skill confinement needs Linux Landlock. On a machine without it, such as a Mac, turn confinement off with its setting on [[Skill Packs]] so skills can run in chats.

## Isolation (local)

`./run-compose.sh --isolation=MODE` sets the skill-isolation variables and starts any extra service that mode needs. What those settings do is on [[Skill Packs]] and [[Tool Runner]]. The [[Tool Runner]] status in the top bar appears only for `--isolation=emulator` (and for a real k8s runner in a cluster).

| `--isolation=` | When to use | What starts |
|-|-|-|
| `off` (default) | Usual on a Mac, or any host without Landlock | Chat only |
| `landlock` | Linux with Landlock | Chat only |
| `emulator` | Exercise the [[Tool Runner]] UI and path with no cluster | Chat plus the emulator |

The emulator speaks the same claim, bind, and exec APIs as the cluster. There is no isolation. It uses the same runner image as the cluster, so skills have the same tools and the same cached skill packages. The runner working directory is the chat's artifacts folder, on the same Docker volume the app uses. A new runner stays starting for a short time so the top-bar spinner can be seen.

To run the emulator by hand instead of Compose, `uv run --script sandbox/emulator/emulator.py` and point the backend at `http://127.0.0.1:18080`.

A real cluster is not a local Compose mode. Staging uses `sandbox.isolation=k8s` on [[Deployment]].

## Running the app in Docker

Copy `.env.example` to `.env` once and put secrets and machine settings there (session key, image name, data volume, mail). Isolation and HTTP/2 are flags, not `.env` values.

`--testing` starts Caddy so the browser uses HTTP/2 at `https://localhost:3443` (or `CADDY_HTTPS_PORT`). Use `https://`, not `http://`, on that port. `http://localhost` redirects there. Live chat on that port needs the Caddy local certificate in the system keychain (Always Trust); otherwise the page can load and the websocket cannot. Without `--testing`, open the app on port 3000 (or `OPEN_WEBUI_PORT`).

If a container named `weather-skills-chat` or `weather-skills-h2` was started by hand, remove it first so Compose can reuse the names. The data volume `weather-skills-chat-data` stays.

```bash
docker rm -f weather-skills-chat weather-skills-h2
./run-compose.sh --testing --isolation=emulator -q --build
```

`-q` skips the confirmation prompt. Leave off `--build` when the image is already current.

| Option | Effect |
|-|-|
| `--testing` | Start Caddy for HTTP/2 |
| `--isolation=off` | Skills on the chat server, no Landlock (default) |
| `--isolation=landlock` | Skills on the chat server with Landlock |
| `--isolation=emulator` | k8s tool-runner path plus the local emulator |
| `--build` | Builds the image from the checkout before starting |
| `--webui[port=PORT]` | Serves the app on `PORT` in place of `OPEN_WEBUI_PORT` |
| `--ollama` | Also starts an Ollama container, connects the app to it, and turns the Ollama API on |
| `--enable-gpu[count=COUNT]` | Gives the Ollama container `COUNT` GPUs, or `all`; the default is 1. Needs `--ollama` |
| `--enable-api[port=PORT]` | Makes the Ollama API reachable on the host at `PORT`; the default is 11435. Needs `--ollama` |
| `--data[folder=PATH]` | Keeps Ollama's data in the folder `PATH`, `./ollama-data` by default, in place of a Docker volume. Needs `--ollama` |

The app needs a model provider: an OpenAI-compatible provider set with `OPENAI_API_BASE_URL` and `OPENAI_API_KEY`, or Ollama with `--ollama`. With neither, the app keeps its default OpenAI connection to `https://api.openai.com/v1` with no key, which an admin replaces in the admin settings.

`--isolation` and `--testing` export the isolation and URL variables for that run. Compose also passes `ENABLE_OPENAI_API`, `OPENAI_API_BASE_URL`, `OPENAI_API_KEY`, `WEBUI_SECRET_KEY`, `WEBUI_URL`, the built-in email variables, and the settings on [[Tracing]] when they are set in `.env` or the shell. Otherwise the value saved in the admin settings, or the default, applies, as described under how settings are read on [[Deployment]].

| Env var | Default | Effect |
|-|-|-|
| `WEBUI_IMAGE` | `ghcr.io/open-webui/open-webui` | Name of the image the stack builds and runs |
| `WEBUI_DOCKER_TAG` | `main` | Tag of that image |
| `WEBUI_CONTAINER_NAME` | `open-webui` | Name of the app's container |
| `WEBUI_DATA_VOLUME` | `weather-skills-chat-data` | Docker volume mounted at the app's data directory |
| `CADDY_HTTPS_PORT` | `3443` | Host port for Caddy when `--testing` is on |

`.env.example` sets these to names of their own, so a local build does not replace an image or collide with a container of another stack on the same Docker host.

## Tests

`docker compose --profile suite run --rm --build test` runs the backend test suite in a container built from the app image with the development packages added. It needs no database server and no access to Docker from inside the container.

CI also builds the tool runner image and writes a Plotly PNG in it, so a skill that renders a figure can use the browser in that image.

## Browser tests

`npm run test:e2e` runs the Playwright browser tests against an app that is already running. Install the browser once with `npx playwright install chromium`.

The tests sign in as the first admin, so the app must start with an empty database and the `BOOTSTRAP_ADMIN_*` settings on [[Deployment]]. They also need `ENABLE_E2E_FIXTURES` on the app.

| Env var | Set on | Default | Effect |
|-|-|-|-|
| `ENABLE_E2E_FIXTURES` | The app | `false` | Turns on test-only actions the browser tests use: deleting every chat of the signed-in user, and back-dating a chat so the chat list files it under an older day. Never set it on staging or production. |
| `PLAYWRIGHT_BASE_URL` | The test run | `http://127.0.0.1:3000` | Address of the app under test |
| `PLAYWRIGHT_API_URL` | The test run | `PLAYWRIGHT_BASE_URL` | Address the tests use to set up chats directly, when it differs from the page address |
| `E2E_ADMIN_EMAIL`, `E2E_ADMIN_PASSWORD`, `E2E_ADMIN_NAME` | The test run | `admin@example.com`, `password`, `Admin` | The first admin's account, matching the app's `BOOTSTRAP_ADMIN_*` settings |

## Skill smoke test

`scripts/smoke_skills.py` checks the whole skill pipeline against the configured database and folders: it installs a small test skill pack, checks the tool made from it, runs the skill in a test chat, and checks that bad secret names and non-https pack addresses are refused. It prints `ALL-SMOKE-OK` when every check passes. The test pack, its tool, and the test chat's files are left in place afterward.
