# Tool runner

- [`emulator/`](emulator/) — a laptop stand-in for the claim / bind / exec APIs. No isolation. Compose runs it on the runner image.

The image that runs inside a GKE Agent Sandbox pod (`sandbox_runtime.py`, Dockerfile, image tests) is in [rhiza-research/infrastructure](https://github.com/rhiza-research/infrastructure) under `images/sandbox-runner`.
