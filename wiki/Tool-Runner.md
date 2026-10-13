# Tool Runner

A tool runner is an isolated place where [[Skill Packs]] run for a saved chat. The top-bar status shows **Weather skills runner paused** when that chat has no runner, or **Weather skills runner starting** / **Weather skills runner ready** if one is already starting or ready. Sending a message starts a runner if none is running. It stays ready while the chat is in use, and stops after ten minutes idle. Sending again after it has stopped starts it again. If that runner dies while the chat is open, the next skill starts a new one and the top bar goes back to starting, then ready. Temporary chats do not get a runner.

The runner is the only place skills run when it is turned on. Built-in tools and the code interpreter stay on the chat server.

## What the user sees

When a k8s tool runner is on (a real runner or the local emulator), an open saved chat shows **Weather skills runner paused**, **Weather skills runner starting**, or **Weather skills runner ready** on the right side of the top bar, to the left of Artifacts and the user menu. Paused means this chat has no runner yet, or the last one has stopped. Sending a message moves it from paused to starting. Ready means the runner is up and the installed skill packs are already on it. Packs are copied when the runner starts, not when each skill runs. Starting becomes ready without a refresh. A green dot pulses slowly when it is ready; a spinner shows while it starts; a gray dot shows when it is paused. Small text under the starting or ready status shows this chat's runner CPU and memory used of that runner's limits on the node (`0 / 3 CPU - 0 / 12 GB Memory` until the first sample, then `0.2 / 3 CPU - 0.4 / 12 GB Memory`). Those figures update while the chat is open, including in other tabs of the same chat. Click the ready status for current CPU, memory, and a **Memory, last minute** chart. That chart is one bar per sample from the last minute; a bar turns red if the runner was using disk swap. Landlock chats do not show it. It is hidden on temporary chats and when the k8s tool-runner path is off.

## Waiting

If a skill is called before the runner is ready — the first send, after the ten-minute idle stop, or while no runner pod is available — the assistant keeps **Waiting for model…** (or switches to **Waiting on weather skills runner**) until a runner is ready. Tool cards do not appear while the runner is paused or still starting. When it is ready, thinking ends and the tool call shows in the same update. A skill that cannot start in time fails.

Each skill call that does run resets the ten-minute idle timer.

## Logs

The runner pod's container log shows when it starts, which skill it is running, and that skill's own output. Readiness checks, pack listings, and CPU/memory samples are not repeated there after the first one.

## Automations

An automation that calls a skill uses the same runner for that chat.

## Disk space

Each chat's files have a two-hundred-gigabyte ceiling so one chat cannot fill the shared store. A skill can write files and folders anywhere under that chat's space, including nested folders created in the chat (for example with `create_folder`). See [[Chat Artifacts]]. A skill that hits the ceiling fails with a write error. Deleting a chat drops the runner. The chat's files are removed as on [[Chat Artifacts]].

## Settings

| Env var | Default | Effect |
|-|-|-|
| `SKILL_SANDBOX_BACKEND` | `landlock` | `landlock` confines skills on the chat server; `k8s` sends skills to a tool runner |
| `SKILL_K8S_SANDBOX_ENABLED` | `false` | Turns the tool-runner path on when the backend is `k8s` |
| `SKILL_K8S_EMULATOR` | unset | When true, chat talks to the local emulator instead of a cluster. No isolation. |
| `SKILL_K8S_TTL_SECONDS` | `600` | Idle time, in seconds, before a runner stops |
| `SKILL_K8S_QUOTA_GIB` | `200` | Ceiling, in gibibytes, for one chat's files |

The Helm chart sets these when `sandbox.isolation` is `k8s`. Staging uses that. Production still confines skills on the chat server. The chart default is `off`. See [[Skill Packs]] and [[Deployment]].

On a laptop, `sandbox/emulator/emulator.py` speaks the same claim, bind, exec, and metrics APIs with no cluster and no isolation. The top-bar status shows CPU and memory of the local process. See [[Development]].

You can check that the real runner pool works without turning chat onto `k8s`. From a machine that can reach the cluster, the Weather Skills sandbox lifecycle test in the infrastructure repository (`tests/weather-skills-sandbox`) claims a runner, binds that chat's files, runs a skill through the same client the chat server uses, and writes a Plotly PNG so the runner image's browser is used.
