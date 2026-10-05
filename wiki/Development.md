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

## Running the app in Docker

`./run-compose.sh` starts the app in Docker with Docker Compose. The app listens on port 3000, or on `OPEN_WEBUI_PORT`. Settings are read from a `.env` file in the repository root; `.env.example` lists the ones the local stack uses.

| Option | Effect |
|-|-|
| `--build` | Builds the image from the checkout before starting |
| `--webui[port=PORT]` | Serves the app on `PORT` in place of `OPEN_WEBUI_PORT` |
| `--ollama` | Also starts an Ollama container, connects the app to it, and turns the Ollama API on |
| `--enable-gpu[count=COUNT]` | Gives the Ollama container `COUNT` GPUs, or `all`; the default is 1. Needs `--ollama` |
| `--enable-api[port=PORT]` | Makes the Ollama API reachable on the host at `PORT`; the default is 11435. Needs `--ollama` |
| `--data[folder=PATH]` | Keeps Ollama's data in the folder `PATH`, `./ollama-data` by default, in place of a Docker volume. Needs `--ollama` |

The app needs a model provider: an OpenAI-compatible provider set with `OPENAI_API_BASE_URL` and `OPENAI_API_KEY`, or Ollama with `--ollama`. With neither, the app keeps its default OpenAI connection to `https://api.openai.com/v1` with no key, which an admin replaces in the admin settings.

Compose passes `ENABLE_OPENAI_API`, `OPENAI_API_BASE_URL`, `OPENAI_API_KEY`, `WEBUI_SECRET_KEY`, and `SKILL_SANDLOCK` to the app only when they are set in `.env` or the shell. Otherwise the value saved in the admin settings, or the default, applies, as described under how settings are read on [[Deployment]].

| Env var | Default | Effect |
|-|-|-|
| `WEBUI_IMAGE` | `ghcr.io/open-webui/open-webui` | Name of the image the stack builds and runs |
| `WEBUI_DOCKER_TAG` | `main` | Tag of that image |
| `WEBUI_CONTAINER_NAME` | `open-webui` | Name of the app's container |

`.env.example` sets these to names of their own, so a local build does not replace an image or collide with a container of another stack on the same Docker host.

## Tests

`docker compose --profile suite run --rm --build test` runs the backend test suite in a container built from the app image with the development packages added. It needs no database server and no access to Docker from inside the container.

## Skill smoke test

`scripts/smoke_skills.py` checks the whole skill pipeline against the configured database and folders: it installs a small test skill pack, checks the tool made from it, runs the skill in a test chat, and checks that bad secret names and non-https pack addresses are refused. It prints `ALL-SMOKE-OK` when every check passes. The test pack, its tool, and the test chat's files are left in place afterward.
