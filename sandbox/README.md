# Tool runner

Two pieces live here:

- [`runtime/`](runtime/) — the image that runs inside a GKE Agent Sandbox pod (`sandbox_runtime.py`, Dockerfile, image tests).
- [`emulator/`](emulator/) — a laptop stand-in for the claim / bind / exec APIs. No isolation. Compose runs it on the runtime image.
