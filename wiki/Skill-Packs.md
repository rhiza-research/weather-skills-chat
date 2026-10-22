# Skill Packs

A skill is a small Python program that does one weather task, such as fetching a forecast, cutting data to a region, or drawing a map. A skill pack is a public git repository that holds one or more skills. Once a pack is installed, the model can run its skills as tools in a chat, and their output lands in the chat's files described on [[Chat Artifacts]].

Admins manage skill packs on the Skills page of the admin settings or the Workspace.

## What a pack contains

Each skill is a folder with a `SKILL.md` file and a `scripts` folder of Python scripts. `SKILL.md` gives the skill's name, description, and version, and a Usage section that explains how to call it. The model sees the description and usage when it decides which skill to run. Folders without scripts are not skills, and a repository with no skills cannot be installed.

## Installing a pack

An admin installs a pack from its `https://` git address and a branch, tag, or commit. The default is `main`.

- A platform admin, with the platform organization active, installs public packs. These are part of the public catalog on [[Organizations]] and appear in every organization.
- An organization admin installs packs private to their organization, when a platform admin has allowed that organization to add skills.

An organization can install the same address and branch only once. To get newer code, update the pack.

## Managing a pack

- Update fetches the latest code for the pack's branch, or switches it to another branch, tag, or commit. Skills that were added appear as tools, and skills that were removed disappear.
- Resync rebuilds every pack's tools from the installed code without fetching anything. Platform admins can run it, and the app also does it when it starts.
- Delete removes the pack and its tools.

Only one install, update, or delete runs at a time on each server. Starting another while one is running is refused, and the admin tries again once the first finishes.

## Turning packs and skills on and off

Packs follow the catalog rules on [[Organizations]]: a platform admin decides whether a public pack starts on or off and can withdraw it everywhere, and each organization's admins can turn it on or off for their organization. The same controls exist for each skill inside a pack, so an organization can use a pack but leave some of its skills off.

The model can run a skill only when both the pack and the skill are on for the chat's organization (see [[Organizations]]).

When two packs offer a skill with the same name, the model runs the one with the highest version number.

## Choosing skills in a chat

A new chat starts with every skill the user can use turned on. The wrench button beside the message box shows how many are on and opens the list of skills and Workspace tools, where the user turns each one on or off for that chat. The list can be searched by name. Descriptions are hidden until the user opens a skill's row.

If the model calls a skill that is off for the message, the skill does not run, and the model is told to tell the user to turn it on there and send the message again.

## When a skill runs

The model chooses a skill, its arguments, and, for skills with several scripts, which script to run. It can also ask for [[Secrets]], which the skill receives as environment variables. The skill runs on the server, inside the chat's files, so what it writes appears in the chat. When a [[Tool Runner]] is on, the skill runs there instead of on the chat server. The user can stop a running skill with the Stop button, and a skill that runs too long is stopped. The model then sees the skill's output and whether it succeeded.

Each skill brings its own Python dependencies, which `uv` installs the first time they are needed and reuses afterward.

## Confinement

On Linux servers, the app can confine each skill run in a chat with Landlock. A confined skill can read only system files, its own pack, and its dependencies, and can write only to the chat's files, temporary files, and its dependency cache. Network access is not restricted. If the server cannot confine a skill while confinement is on, the skill does not run.

When a [[Tool Runner]] is on, Landlock is not used for that skill. The runner itself is the isolation.

## Skill environments

When confinement is on, dependencies are kept in an environment per chat, on the volume set by `SKILL_VENV_ROOT`. When the volume fills past the space set by `SKILL_VENV_MAX_BYTES`, the environments of the chats used least recently are removed, and are rebuilt if those chats run skills again. Without that volume, each user gets one shared cache instead.

## Settings

| Env var | Default | Effect |
|-|-|-|
| `SKILL_SANDLOCK` | `true` | Confine skill runs in chats on the chat server |
| `SKILL_LANDLOCK_BACKEND` | `auto` | Which Landlock method to use when confinement is on: `auto` picks the best the server supports; `sandlock` and `landlock_only` force one |

The Helm chart sets those from one value, `sandbox.isolation`. `off` turns confinement off. `auto`, `sandlock`, and `landlock_only` confine on the chat server. `k8s` sends skills to a [[Tool Runner]] instead. Staging and production both use `k8s`. See [[Deployment]].
| `SKILL_RUN_TIMEOUT` | `600` | How long, in seconds, a skill may run before it is stopped, unless the model asks for a different `timeout` on that call |
| `SKILL_RUN_TIMEOUT_MAX` | `1800` | The longest `timeout`, in seconds, the model may ask for on one call; longer requests are cut to this |
| `SKILL_VENV_ROOT` | `/var/skill-venvs` | Volume for per-chat skill environments; used only when it exists and the app can write to it |
| `SKILL_VENV_MAX_BYTES` | `0` | Space, in bytes, that per-chat environments may use; `0` means 85% of the volume |
| `SKILLS_DIR` | `<DATA_DIR>/skills` | Where installed packs are stored |
| `UV_CACHE_DIR` | `<DATA_DIR>/uv-cache` | Dependency cache when confinement is off |
| `USER_CACHES_DIR` | `<DATA_DIR>/user_caches` | Per-user dependency caches when confinement is on and there is no per-chat volume |
| `SKILL_PACK_COPY_WORKERS` | The number of CPUs | How many files are copied at once when a pack is installed or updated |

The server needs `git` to install packs and `uv` to run skills.
