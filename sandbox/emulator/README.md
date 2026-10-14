# Tool runner emulator

Laptop stand-in for the APIs chat uses on GKE: SandboxClaim, the bind daemon (`/bind`, `/own`, `/quota`, `/unbind`, `/metrics`), and the runner `/exec` server. There is no isolation. Chat sends `/workspace/chat` the same way it does on the cluster; the emulator maps that onto the chat's artifacts folder. `/workspace/.skill-packs` maps inside the artifacts folder. Skill packages use the image uv cache at `/opt/uv-cache` (the same path chat sets as `UV_CACHE_DIR` on the cluster). Compose runs this on the same image as the cluster runner (`sandbox/runtime`), so skill exec has the same tools. Chat reads CPU and memory from the bind daemon `/metrics` URL; the emulator fills that from the local process.

Compose starts this service when you pass `--isolation=emulator` to `./run-compose.sh`. See `wiki/Development.md`. Compose waits 15 seconds before a new claim is ready so the top-bar starting status can be seen; set `SKILL_K8S_EMULATOR_START_DELAY=0` to turn that off.

To run it by hand:

```bash
uv run --script sandbox/emulator/emulator.py
```

Point the backend at it with `SKILL_SANDBOX_BACKEND=k8s`, `SKILL_K8S_SANDBOX_ENABLED=true`, `SKILL_K8S_EMULATOR=true`, and `SKILL_K8S_BIND_TOKEN=dev`.
