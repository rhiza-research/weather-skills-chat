# MCP Endpoint

Weather Skills Chat serves an MCP endpoint, so MCP clients such as Claude Code and claude.ai can run the weather skills from [[Skill Packs]] for a user's account, outside a chat in the app.

## Connecting a client

Settings > MCP in the app shows the endpoint's address, with a button to copy it, and how to connect:

- Claude Code: a command that adds the endpoint, then `/mcp` in Claude Code to sign in.
- claude.ai: add a custom connector with the endpoint's address.
- Other MCP clients: give the client the endpoint's address.

## Signing in

A client must sign in to an account before it can list or run anything. When a client connects, it opens a browser at the app. The user signs in to the app if they are not signed in already, and a page names the client and the account and asks the user to approve or deny the client. Once approved, the client acts as that account. It renews its sign-in without asking the user again, until the sign-in expires after a period without use or is revoked.

Accounts waiting for approval cannot approve a client or use the endpoint. The account's role is checked on every call, so an account that loses its access in the app also loses it on the endpoint.

After approval, the browser returns to the client. Only `http` addresses on the local machine are always allowed, which covers a client such as Claude Code running on the user's machine. Any other return address must be listed in `MCP_OAUTH_ALLOWED_REDIRECT_URIS`. claude.ai returns to its own address, so it can connect only when that address is listed.

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

The endpoint's address is the app's public address, `WEBUI_URL` on [[Deployment]], followed by `/mcp/`. The values `WEBUI_URL` may take are listed there. The endpoint reads it when the app starts, so a change made in the admin settings applies to the endpoint after a restart.

| Env var | Default | Effect |
|-|-|-|
| `REDIS_URL` | empty | Redis server that one-time links are kept in. When it is empty, one-time links are refused. Open WebUI also keeps its settings in this Redis when it is set. |
| `MCP_OAUTH_ALLOWED_REDIRECT_URIS` | empty | Comma-separated return addresses, besides local `http` addresses, that the browser may go back to after a user approves a client. Each entry is an exact address, or a prefix ending in `*`. A prefix entry matches an address whose scheme, host, and port equal the entry's exactly and whose path starts with the rest of the entry. Empty allows only local `http` addresses. |

## Removing old sign-in records

The app keeps a record of each client that registered and of each approval. The command `python -m open_webui.mcp_oauth.retention`, run from `/app/backend` inside an app container or pod so that it uses the app's environment and database, deletes the records that can no longer be used. It also removes a registered client that has no sign-in in use 30 days after the client registered. Nothing runs the command automatically, so schedule it.
