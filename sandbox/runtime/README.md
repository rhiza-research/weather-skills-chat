# Tool runner image

This is the container that runs inside a GKE Agent Sandbox pod. It is not the chat app.

The image is published as `ghcr.io/rhiza-research/weather-skills-chat-sandbox` from `.github/workflows/docker-publish.yml` on pushes to `dev` and `main` (same tags as the chat image: branch, `sha-…`, semver).

## What is in the image

- `uv` and CPython 3.11 / 3.12, so a skill can `uv run --script`
- A uv package cache at `/opt/uv-cache`, filled at image build from the Weather Skills catalog on `main`. Chat sets `UV_CACHE_DIR` to that same path. `/workspace` is an emptyDir on the cluster, so the cache cannot live there.
- Chromium and the shared libraries Kaleido 1+ needs for Plotly `write_image`
- `sandbox_runtime.py`, an HTTP server on port 8888

CI runs `tests/plotly_png_check.py` in this image to prove Plotly can write a PNG. `tests/test_sandbox_runtime.py` covers the HTTP helpers without Docker.

The process writes to stdout (the container log): startup, each `/exec` and `/unpack`, the skill name, and the skill's own stdout/stderr. Readiness, pack listings, and metrics polls are logged once so they do not drown skill output.

Chat talks to a specific runner pod. It does not import this Python file.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Readiness |
| `GET` | `/packs` | Names of skill packs already on the runner |
| `GET` | `/metrics` | Optional process snapshot; the chat UI reads node cgroup metrics from the bind daemon |
| `POST` | `/exec` | Run a command (`cmd`, optional `cwd`, `env`, `timeout`) and return stdout, stderr, exit code |
| `POST` | `/unpack` | Extract a gzip tar (`dest`, `archive`) under the workspace |

This runtime is a stand-in until we switch the pod to `sandboxd`. Bind/unbind of JuiceFS is a node daemon, not this process.

## Build locally

```bash
docker build -t weather-skills-chat-sandbox ./sandbox/runtime
```

The build clones the Weather Skills catalog on `main` and `uv export --script` / `uv pip install`s each skill script so wheels land in `/opt/uv-cache`. `PREWARM=false` skips that for a faster local image that still talks the runtime protocol.

```bash
docker build --build-arg PREWARM=false -t weather-skills-chat-sandbox ./sandbox/runtime
```
