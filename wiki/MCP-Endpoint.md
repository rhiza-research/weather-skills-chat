# MCP Endpoint

Weather Skills Chat serves an MCP endpoint, so MCP clients such as Claude Code and claude.ai can run the weather skills from [[Skill Packs]] for a user's account, outside a chat in the app.

## Connecting a client

Settings > MCP in the app shows the endpoint's address, with a button to copy it, and how to connect:

- Claude Code: a command that adds the endpoint, then `/mcp` in Claude Code to sign in.
- claude.ai: add a custom connector with the endpoint's address.
- Other MCP clients: give the client the endpoint's address.

## Organizations

Each call runs in one organization: the user's personal organization, unless the client sends an organization header naming another organization the user is a member of. Settings > MCP shows that header for the organization active in the app, and the Claude Code command includes it. A call that names an organization the user is not a member of, or an inactive one, is refused.

The organization decides which skills the client sees and which [[Secrets]] a skill receives, as it does in a chat. Organizations are described on [[Organizations]].

## What a client can do

- Run the skills that are on for the user in the organization. Workspace tools, and the built-in tools the model has in a chat, are not offered.
- List the session's files with `list_artifacts`.
- Fetch one file with `get_artifact`, in one of these forms:
  - Its content, for a text file or an image.
  - Its bytes, as base64 text.
  - A link that works for someone signed in to the app.
  - A one-time link that serves the file once without signing in, for downloading from a shell. One-time links need `REDIS_URL`; without it the client is told to use another form.

Large results are shortened, and the client is told how much was kept.

## The session chat

Each tool a client runs, including `list_artifacts` and `get_artifact`, is recorded with its arguments and result in a private chat titled "MCP session", one per user and organization. Asking for the list of tools is not recorded. Skills run in that chat's files, so what they write appears in its files, described on [[Chat Artifacts]].

The user can open the session chat in the app and rename it, but cannot change its messages. A tab that has it open shows new calls after a reload.

## Settings

The endpoint's address is the app's public address, `WEBUI_URL` on [[Deployment]], followed by `/mcp/`. The app does not start when `WEBUI_URL` is empty.

| Env var | Default | Effect |
|-|-|-|
| `REDIS_URL` | empty | Redis server that one-time links are kept in. When it is empty, one-time links are refused. Open WebUI also keeps its settings in this Redis when it is set. |
