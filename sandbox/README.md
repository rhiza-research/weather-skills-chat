# Tool runner image

This folder is the container that runs inside a GKE Agent Sandbox pod. It is not the chat app.

The image is published as `ghcr.io/rhiza-research/weather-skills-chat-sandbox` from `.github/workflows/docker-publish.yml` on pushes to `dev` and `main` (same tags as the chat image: branch, `sha-…`, semver).

## What is in the image

- `uv` and CPython 3.11 / 3.12, so a skill can `uv run --script`
- Chromium and the shared libraries Kaleido 1+ needs for Plotly `write_image`
- `sandbox_runtime.py`, an HTTP server on port 8888

Chat and local probes talk to a specific runner pod. They do not import this Python file.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Readiness |
| `GET` | `/metrics` | cgroup CPU, memory, and swap for the UI |
| `POST` | `/exec` | Run a command (`cmd`, optional `cwd`, `env`, `timeout`) and return stdout, stderr, exit code |

This runtime is a stand-in until we switch the pod to `sandboxd`. Bind/unbind of JuiceFS is a node daemon, not this process.

## Build locally

```bash
docker build -t weather-skills-chat-sandbox ./sandbox
```
