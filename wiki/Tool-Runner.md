# Tool Runner

A tool runner is an isolated place where [[Skill Packs]] run for a saved chat. The top-bar status shows **Weather skills runner paused** when that chat has no runner, or **Weather skills runner starting** / **Weather skills runner ready** if one is already starting or ready, or **Weather skills runner degraded** if it is up but unhealthy. Sending a message starts a runner if none is running. It stays ready while the chat is in use, and stops after it has been idle for its size's idle time (ten minutes for the standard size; see [Runner sizes](#runner-sizes)). Sending again after it has stopped starts it again. A runner that is in use for a chat stays on its machine; unused spare runners can be moved when the pool shrinks. If the runner dies while a skill is running, or its connection to the chat's files breaks, that skill fails with an error telling the model the sandbox runner died for reasons not clearly related to its call, and to try again. If the runner ran out of memory, the error says so and suggests doing less at once. The model is told that only this error means a call used too much memory, so for other runner failures it first retries the same call before doing less. If the request simply did not reach a runner that is still up, for example when many skills start at once, the error says the runner may be overloaded and to try fewer tool calls at once or try again shortly, and the runner is kept. A runner is replaced only when it reports itself unhealthy or Kubernetes reports it gone or not ready; a slow answer alone does not replace it. While a skill runs, the chat checks the runner's health every few seconds and replaces it as soon as it reports itself unhealthy. A runner that stays not ready for about 40 seconds is also released by the cluster. The top bar follows each step: degraded when the runner reports itself unhealthy or goes not ready, paused once it is released, and starting while a new one comes up. The next skill waits for the new runner. If a runner dies or loses its files between skills, the next skill waits for a new runner instead of failing. Temporary chats do not get a runner.

The runner is the only place skills run when it is turned on. Built-in tools and the code interpreter stay on the chat server.

The runner image already holds the Python packages the Weather Skills catalog skills declare. The first skill on a new runner reuses that cache instead of downloading those packages. A skill that needs something else still downloads it on first use.

## What the user sees

When a k8s tool runner is on (a real runner or the local emulator), an open saved chat shows **Weather skills runner paused**, **Weather skills runner starting**, **Weather skills runner ready**, or **Weather skills runner degraded** on the right side of the top bar, to the left of Artifacts and the user menu. Paused means this chat has no runner yet, or the last one has stopped or is being released. Sending a message moves it from paused to starting. Ready means the runner is up and this organization's active skills are already on it, each at its current version. Those skills are copied when the runner starts. A skill that is turned on, installed, or updated after that is copied before its first call on the runner, so a call never runs a missing or older copy. Starting becomes ready without a refresh. Degraded, in red, means the runner is still assigned to this chat but reports itself unhealthy, Kubernetes marks it not ready, or it has not answered a health check for 30 seconds. A runner that is only silent is left alone; it may just be busy. A green dot pulses slowly when it is ready; a spinner shows while it starts; a gray dot shows when it is paused; a red dot shows when it is degraded. Small text under the starting or ready status shows the runner's size when it is not the standard size, and this chat's runner CPU and memory used of that runner's limits on the node (`0 / 3 CPU - 0 / 12 GB Memory` until the first sample, then `0.2 / 3 CPU - 0.4 / 12 GB Memory`). Those figures update while the chat is open, including in other tabs of the same chat. Click the ready status for current CPU, memory, a **Memory, last minute** chart, and the runner size picker described under [Runner sizes](#runner-sizes). In any other state, clicking the status shows only the size picker. That chart is one bar per sample from the last minute; a bar turns red if the runner had more than 500 MB in disk swap. A little swap can stay in use after memory pressure has passed, so smaller amounts are not shown. Landlock chats do not show it. It is hidden on temporary chats and when the k8s tool-runner path is off.

Opening a skill call in the chat shows its output. For a skill that ran on the runner, a last line gives the skill's CPU time, the peak memory of its largest process, and how long it ran. Runner images that do not report these figures show no such line.

## Waiting

If a skill is called before the runner is ready — the first send, after the idle stop, after a runner died, after a switch to another size, or while no runner pod is available — the assistant keeps **Waiting for model…** (or switches to **Waiting on weather skills runner**) until a runner is ready. For a size other than the standard one the line names the size, and for a size with no runners kept ready it adds that it can take a few minutes to start. A runner is ready once it is claimed for the chat, the chat's files are connected to it, and the organization's skills are copied onto it. Each of those steps is tried again while waiting, up to the size's start time limit. Skill calls are not listed while the runner is paused or still starting. When it is ready, that same line updates to the skill that is running. If no runner is ready within the limit, the skill fails with an error asking to try again.

While the model is still writing its tool calls, the assistant shows **Preparing tool calls… (Ns)**, counting the seconds. The tool calls appear once the model has finished writing all of them, which can take several seconds for a batch of parallel calls; how many there are is not known until then.

A running skill keeps the runner for at least that skill's run timeout (see [[Skill Packs]]), even if the runner was already ready. The model can set a longer `timeout` on a call, up to 30 minutes. A skill still running at its timeout is stopped on the runner, along with everything it started, and the model is told it did not finish within its timeout and can retry with a larger timeout or less work. Pressing Stop in the chat also stops the skill on the runner, not just the wait for it. After the last skill, the runner still stops after its idle time.

## Logs

The runner pod's container log shows when it starts, which skill it is running, and that skill's own output. Runtime failures such as unpack or storage errors are written as errors; a skill that exits non-zero is not. Readiness checks, pack listings, and CPU/memory samples are not repeated there after the first one. The chat server log names the chat and the runner pod for each skill call, including when a dead runner is dropped and the next skill starts a replacement.

## Runner sizes

The cluster offers tool runners in several sizes, each with its own CPU and memory limits. Staging and production offer:

| Size | CPU and memory | Runners kept ready | Idle time | Needs approval |
|-|-|-|-|-|
| Standard | 8 CPU, 8 GB | Yes | 10 minutes | No |
| Medium | 8 CPU, 16 GB | No; starts in seconds to about 2 minutes | 10 minutes | No |
| Large | 8 CPU, 52 GB | No; about 2 minutes | 5 minutes | Yes |
| XLarge | 16 CPU, 108 GB | No; about 2 minutes | 5 minutes | Yes |

The sizes, their limits, and which ones need approval are set in the infrastructure repository's runner chart; the chat reads them from the cluster. A cluster that publishes no sizes offers only the standard runner.

Every chat starts on the standard size. It can be switched in two ways:

- **By the user.** The runner size picker in the status menu lists the sizes this chat's organization can use, with each one's CPU, memory, and description. Choosing one switches the chat at once. The user choosing a size counts as approving it.
- **By the model**, with the `request_tool_runner` tool on [[Built-in Tools]]. The model is told which sizes the chat can use, which one it is on, and which need approval. A runner that ran out of memory also tells the model it can ask for a larger size when there is one. Switching to a size that needs approval, when it is larger than the current one, first asks the user in a popup that shows the size, its limits, how long it takes to start, and the model's reason. Declining leaves the runner as it is. Switching to a smaller size, or to a size that does not need approval, does not ask.

After a switch, skill calls run on a runner of the new size, which starts right away. Skill calls already running finish on the previous runner, which is released once its last call ends. Both runners see the same chat files. A chat on another size than the standard one goes back to the standard size once that runner has been idle for its idle time, so the next send gets a standard runner.

Sizes that need approval are available only to organizations a platform admin has allowed to use large runners, and to the platform organization. See [[Organizations]].

The chosen size is kept by the chat server while it runs. Restarting the chat server puts every chat back on the standard size; a runner of another size still running then stops after its idle time.

## Scheduled tasks

A [[Scheduled Tasks]] run that calls a skill uses the same runner for that chat. A task can name a runner size; each run then starts on that size. Choosing a size on the task counts as approving it, since no one is present during a run to approve one. A run whose organization can no longer use the task's size uses the standard size. During a run, the model can switch to a size that does not need approval, but not to one that does.

## Disk space

Each chat's files have a two-hundred-gigabyte ceiling so one chat cannot fill the shared store. A skill can write files and folders anywhere under that chat's space, including nested folders created in the chat (for example with `create_folder`). See [[Chat Artifacts]]. A skill that hits the ceiling fails with a write error. Deleting a chat drops the runner. The chat's files are removed as on [[Chat Artifacts]].

## Settings

| Env var | Default | Effect |
|-|-|-|
| `SKILL_SANDBOX_BACKEND` | `landlock` | `landlock` confines skills on the chat server; `k8s` sends skills to a tool runner |
| `SKILL_K8S_SANDBOX_ENABLED` | `false` | Turns the tool-runner path on when the backend is `k8s` |
| `SKILL_K8S_EMULATOR` | unset | When true, chat talks to the local emulator instead of a cluster. No isolation. |
| `SKILL_K8S_TTL_SECONDS` | `600` | Idle time, in seconds, before a runner stops, for a size whose cluster settings set none |
| `SKILL_K8S_START_TIMEOUT_SECONDS` | `180` | Time limit, in seconds, for getting a runner ready before a skill fails, for a size whose cluster settings set none |
| `SKILL_K8S_QUOTA_GIB` | `200` | Ceiling, in gibibytes, for one chat's files |

The Helm chart sets these when `sandbox.isolation` is `k8s`. Staging and production both use that. The chart default is `off`. See [[Skill Packs]] and [[Deployment]].

On a laptop, `sandbox/emulator/emulator.py` speaks the same claim, bind, exec, and metrics APIs with no cluster and no isolation, and offers the same runner sizes. The top-bar status shows CPU and memory of the local process against the size's limits. See [[Development]].

You can check that the real runner pool works without turning chat onto `k8s`. From a machine that can reach the cluster, the Weather Skills sandbox lifecycle test in the infrastructure repository (`tests/weather-skills-sandbox`) claims a runner, binds that chat's files, runs a skill through the same client the chat server uses, and writes a Plotly PNG so the runner image's browser is used.
