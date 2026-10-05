# Deployment

Weather Skills Chat runs as one container image, usually on Kubernetes with the project's Helm chart.

## Container image

The image is published as `ghcr.io/rhiza-research/weather-skills-chat` for `linux/amd64`. Images are built from the `main` and `dev` branches and from release tags shaped like `vX.Y.Z` or `vX.Y.Z-<suffix>`. Each image is tagged with its branch or release version and with its commit, and builds of `main`, the default branch, are also tagged `latest`.

The image includes Python and the `git` and `uv` tools that [[Skill Packs]] need. The speech, embedding, and tokenizer models are built into the image outside the data directory, so mounting a data volume does not hide them.

| Env var | Default | Effect |
|-|-|-|
| `MODEL_CACHE_DIR` | `/app/backend/cache` in the image; `backend/cache` in a source checkout | Where the app loads the built-in models from |

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
- `sandbox.skillSandlock` is off by default, which turns off the skill confinement described on [[Skill Packs]].
- `skillVenvs.enabled` gives each pod its own volume for skill environments, and `skillVenvs.maxBytes` sets how much of it skills may use. See [[Skill Packs]].
- `langfuse.enabled` turns [[Tracing]] on or off.

## How settings are read

Many settings can be changed by an admin while the app runs, and the app stores the new value. When a setting's variable is present in the server's environment, the environment always wins, even when its value is empty, and changes made in the app are ignored. When the variable is absent, the app uses the stored value, unless `ENABLE_PERSISTENT_CONFIG` is false, in which case it uses the built-in default. `ENABLE_PERSISTENT_CONFIG` is true by default.

## Model providers

The app reaches models through OpenAI-compatible providers and Ollama servers, which admins set up in the admin settings.

| Env var | Default | Effect |
|-|-|-|
| `ENABLE_OLLAMA_API` | `false` | Connects the app to Ollama servers. When it is off, the app does not look for an Ollama server. |

The Helm chart sets `ENABLE_OLLAMA_API` from `ollama.enabled`, which is `false` by default. In a chart deployment the chart therefore decides whether the Ollama API is on, and turning it on or off in the admin settings has no effect.

## First admin

When the app starts with no users and both `BOOTSTRAP_ADMIN_EMAIL` and `BOOTSTRAP_ADMIN_PASSWORD` are set, it creates one account and makes it the owner of the platform organization. That account is the first platform admin, described on [[Organizations]]. Signup settings are not changed.

| Env var | Default | Effect |
|-|-|-|
| `BOOTSTRAP_ADMIN_EMAIL` | empty | First admin's email |
| `BOOTSTRAP_ADMIN_PASSWORD` | empty | First admin's password |
| `BOOTSTRAP_ADMIN_NAME` | `admin` | First admin's display name |

## Branding and links

| Env var | Default | Effect |
|-|-|-|
| `WEBUI_NAME` | `Weather Skills` | App name |
| `WEBUI_URL` | `http://localhost:3000` | The app's public address, used in links in emails and in what the model sends users |
| `WEBUI_FAVICON_URL` | `<WEBUI_URL>/static/favicon.png` | Browser tab icon |
| `WEBUI_HELP_EMAIL` | `help@weather-skills.org` | Support address shown to users when something fails |
| `WEBUI_IMAGE_TAG` | empty | Release label shown in the app; when empty, the app version is shown. The Helm chart sets it to the image tag. |

## Formatting instruction

| Env var | Default | Effect |
|-|-|-|
| `RENDERING_PROMPT` | "Responses will be interpreted as github markdown. Please use proper escape sequences if you would like to use markdown-specific characters but not render them as markdown" | Instruction added to every chat telling the model how its replies are displayed; empty turns it off |
