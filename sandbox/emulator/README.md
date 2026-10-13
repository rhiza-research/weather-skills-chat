# Tool runner emulator

Laptop stand-in for the three APIs chat uses on GKE: SandboxClaim, the bind daemon, and the runner `/exec` and `/metrics` server. There is no isolation. Chat sends `/workspace/chat` the same way it does on the cluster; the emulator maps that onto the chat's artifacts folder. `/workspace/.uv-cache` maps next to that folder, not inside it. `/workspace/.skill-packs` maps inside the artifacts folder. Compose runs this on the same image as the cluster runner (`sandbox/runtime`), so skill exec has the same tools. Metrics are the local runtime process CPU and RSS.

Compose starts this service when you pass `--isolation=emulator` to `./run-compose.sh`. See `wiki/Development.md`. Compose waits 15 seconds before a new claim is ready so the top-bar starting status can be seen; set `SKILL_K8S_EMULATOR_START_DELAY=0` to turn that off.

To run it by hand:

```bash
uv run --script sandbox/emulator/emulator.py
```

Point the backend at it with `SKILL_SANDBOX_BACKEND=k8s`, `SKILL_K8S_SANDBOX_ENABLED=true`, `SKILL_K8S_EMULATOR=true`, and `SKILL_K8S_BIND_TOKEN=dev`.
