# Deployment

Weather Skills Chat runs as one container image, usually on Kubernetes with the project's Helm chart.

## Container image

The image is published as `ghcr.io/rhiza-research/weather-skills-chat` for `linux/amd64`. Images are built from the `main` and `dev` branches and from release tags shaped like `vX.Y.Z` or `vX.Y.Z-<suffix>`. Each image is tagged with its branch or release version and with its commit, and builds of `main`, the default branch, are also tagged `latest`.

The image includes Python and the `git` and `uv` tools that [[Skill Packs]] need. The speech, embedding, and tokenizer models are built into the image outside the data directory, so mounting a data volume does not hide them.

| Env var | Default | Effect |
|-|-|-|
| `MODEL_CACHE_DIR` | `/app/backend/cache` in the image; `backend/cache` in a source checkout | Where the app loads the built-in models from |
| `RAG_EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | Embedding model the app uses for documents |
| `WHISPER_MODEL` | `base` | Speech-to-text model |
| `TIKTOKEN_ENCODING_NAME` | `cl100k_base` | Tokenizer used to split documents |

The build arguments `USE_EMBEDDING_MODEL`, `WHISPER_MODEL`, and `USE_TIKTOKEN_ENCODING_NAME` only choose which models are built into the image. Their defaults match the defaults above. An image built with other models needs the matching variables above set when it runs.

## Release model

- Pull requests target the `dev` branch, and feature branches are rebased onto `dev`.
- Every push to `dev` builds an image and resets the `staging` branch to that commit, with the chart pinned to the new image. Argo CD deploys staging from the `staging` branch.
- A push to `main` builds an image and deploys nothing.
- A release is a semver tag such as `v1.2.3` or `v1.2.3-rc.1` on a commit that is on `main`. It builds an image and resets the `prod` branch to the tagged commit, with the chart pinned to the release image. Argo CD deploys production from the `prod` branch, so production gets that commit's chart as well as its image. A tag on a commit that is not on `main` is not deployed.
- The workflow owns the `staging` and `prod` branches. Anything committed to them directly is overwritten.
- This wiki is published from `dev`, so it describes what is on staging.

## Helm chart

The chart lives in the repository under `charts/weather-skills-chat`. Its [README](https://github.com/rhiza-research/weather-skills-chat/blob/main/charts/weather-skills-chat/README.md) describes every value, including storage, Postgres, storage for skill data, OAuth sign-in, web search, and OpenTelemetry. The values below change how the app itself behaves.

- `secretName` is required. It names a Kubernetes Secret that you create, which must hold `WEBUI_SECRET_KEY`. The README lists the other keys the chart reads from it.
- `image.tag` selects the app version. By default it follows the chart's `appVersion`.
- By default the app runs as one replica, with SQLite stored on a persistent volume.
- SQLite supports one app process only: one replica, and `UVICORN_WORKERS` left at 1. Running more needs Postgres, or two processes can erase each other's changes to the same chat.
- `sandbox.skillSandlock` is off by default, which turns off the skill confinement described on [[Skill Packs]].
- `skillVenvs.enabled` gives each pod its own volume for skill environments, and `skillVenvs.maxBytes` sets how much of it skills may use. See [[Skill Packs]].
- `langfuse.enabled` turns [[Tracing]] on or off.

## How settings are read

Each setting is read from one environment variable, the one named on these pages. When that variable is set, the app uses its value on every start, and changes made in the admin settings are ignored. For a text setting, an empty value counts as set. When the variable is not set, the admin settings control the setting: the app uses the value last saved there, or the built-in default when nothing was saved or `ENABLE_PERSISTENT_CONFIG` is false. `ENABLE_PERSISTENT_CONFIG` is true by default. The container image sets none of these variables.

Settings that hold a list or a group of values take JSON. When such a variable is empty, is not valid JSON, is the wrong kind of JSON value, or has an entry of the wrong shape or with a key the setting does not have, the app does not start, and the error names the variable. A JSON value replaces the setting's default entirely; nothing from the default is kept.

## Model providers

The app reaches models through OpenAI-compatible providers and Ollama servers, which admins set up in the admin settings or in the environment. Connections are numbered from `0` in the order of their addresses.

| Env var | Default | Effect |
|-|-|-|
| `ENABLE_OLLAMA_API` | `false` | Connects the app to Ollama servers. When it is off, the app does not look for an Ollama server. |
| `OPENAI_API_BASE_URLS` | `https://api.openai.com/v1` | Addresses of the OpenAI-compatible connections, separated by `;` |
| `OPENAI_API_KEYS` | one connection with no key | Keys of those connections, in the same order, separated by `;`. When both this and `OPENAI_API_BASE_URLS` are set, they must have the same number of entries. |
| `OPENAI_API_CONFIGS` | empty | Settings of each OpenAI-compatible connection, as a JSON object keyed by connection number, such as `{"0": {"model_call_tracing": "openrouter"}}`. Model-call tracing is described on [[Tracing]]. |
| `OLLAMA_BASE_URLS` | empty | Addresses of the Ollama servers, separated by `;`. With none set, the app connects to no Ollama server even when `ENABLE_OLLAMA_API` is on. A trailing `/` is removed. |
| `OLLAMA_API_CONFIGS` | empty | Settings of each Ollama connection, as a JSON object keyed by connection number |
| `TOOL_SERVER_CONNECTIONS` | empty | Tool servers, as a JSON array of objects, each with a `url` and the `path` of its OpenAPI description |

In the `;`-separated lists, every entry must be non-empty, so an empty value or a stray `;` stops the app from starting. In the two `_CONFIGS` settings, a connection number must belong to an address the app has.

The Helm chart sets `ENABLE_OLLAMA_API` from `ollama.enabled`, which is `false` by default. In a chart deployment the chart therefore decides whether the Ollama API is on, and turning it on or off in the admin settings has no effect.

## First admin

When the app starts with no users and both `BOOTSTRAP_ADMIN_EMAIL` and `BOOTSTRAP_ADMIN_PASSWORD` are set, it creates one account and makes it the owner of the platform organization. That account is the first platform admin, described on [[Organizations]]. Signup settings are not changed.

| Env var | Default | Effect |
|-|-|-|
| `BOOTSTRAP_ADMIN_EMAIL` | empty | First admin's email |
| `BOOTSTRAP_ADMIN_PASSWORD` | empty | First admin's password |
| `BOOTSTRAP_ADMIN_NAME` | `admin` | First admin's display name |

## Sign-in

| Env var | Default | Effect |
|-|-|-|
| `OAUTH_GROUPS_CLAIM` | `groups` | The sign-in claim that lists a user's groups |
| `LDAP_SEARCH_FILTER` | empty | Extra filter for LDAP user searches |

## Branding and links

| Env var | Default | Effect |
|-|-|-|
| `WEBUI_NAME` | `Weather Skills` | App name |
| `WEBUI_URL` | `http://localhost:3000` | The app's public address, used in links in emails and in what the model sends users |
| `WEBUI_FAVICON_URL` | `<WEBUI_URL>/static/favicon.png` | Browser tab icon |
| `WEBUI_BANNERS` | empty | Banners shown to users, as a JSON array of objects, each with `id`, `type`, `content`, `dismissible`, and `timestamp`, and optionally `title` |
| `WEBUI_HELP_EMAIL` | `help@weather-skills.org` | Support address shown to users when something fails |
| `WEBUI_IMAGE_TAG` | empty | Release label shown in the app; when empty, the app version is shown. The Helm chart sets it to the image tag. |

## Formatting instruction

| Env var | Default | Effect |
|-|-|-|
| `RENDERING_PROMPT` | "Responses will be interpreted as github markdown. Please use proper escape sequences if you would like to use markdown-specific characters but not render them as markdown" | Instruction added to every chat telling the model how its replies are displayed; empty turns it off |

## Other admin settings

| Env var | Default | Effect |
|-|-|-|
| `DEFAULT_PROMPT_SUGGESTIONS` | Four weather examples | Suggestions shown on a new chat, as a JSON array of objects, each with a `title` array of strings and a `content` string |
| `MODEL_ORDER_LIST` | empty | Order of models in the model picker, as a JSON array of model ids |
| `USER_PERMISSIONS` | Built from the `USER_PERMISSIONS_*` variables | Default user permissions, as a JSON object of permission groups, each an object of `true` or `false` flags. It replaces the default entirely, so a group or flag it leaves out is not granted. When it is set, the `USER_PERMISSIONS_*` variables are not used. |
| `EVALUATION_ARENA_MODELS` | empty | Arena models, as a JSON array of objects, each with an `id`, a `name`, and a `meta` object |
| `COMFYUI_WORKFLOW_NODES` | empty | Which ComfyUI workflow nodes receive the image prompt and settings, as a JSON array of objects |
| `IMAGES_GEMINI_API_BASE_URL` | empty | Address of the Gemini image generation API |
| `IMAGES_GEMINI_API_KEY` | empty | Key for the Gemini image generation API |
| `RAG_EMBEDDING_BATCH_SIZE` | `1` | How many texts are sent to the embedding model at once |
| `RAG_OLLAMA_BASE_URL` | empty | Ollama server used for document embeddings when the embedding engine is Ollama |
