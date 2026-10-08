# Live Chat Updates

Chats, the chat list, and each chat's files update on their own while the app is open. A user does not reload the page to see what happened in another browser tab, or what another member did in a shared chat.

## What updates live

- **Messages.** A message sent in one tab appears in every other open tab of the same chat, and the reply streams there as it is written.
- **The chat list.** A chat moves to the top of Today when a message is sent or edited in it, or when it is pinned, archived, moved to a folder, or shared. New chats appear, and deleted chats disappear, in every open tab.
- **Files.** The file list next to a chat updates when a skill or an upload adds or changes files. See [[Chat Artifacts]].
- **Shared chats.** Members of an organization see these updates for chats shared with it, and a deleted chat leaves their open pages. Who can read a chat, and what happens when it stops being shared, is described on [[Organizations]].

## Switching chats

After sign-in, the app keeps the chats used in the past week in the browser, a few of the user's own and a few shared with the active organization. Opening one of them shows it at once, and a newer version, if there is one, loads behind it. Switching organization drops the previous organization's chats from the browser.

## Reading position

Each chat remembers where the user was reading. Coming back to a chat returns to the same place, or to the newest message if the user was at the end. When a reply arrives while the user is reading further up, the page stays where it is and a **New messages** button appears; it scrolls to the newest message. Opening a chat from a reply notice goes to the newest message. Reply sounds and notices are described on [[Notifications]].

## Changes from two places at once

Only a chat's owner can change it, but the owner can have it open in several tabs.

- If the chat changed in another tab since this tab last saw it, a new message is sent again without asking. It is added after the newest message, so the conversation stays in one line.
- If a message cannot be sent, it stays on screen with an error on its reply, and the user can retry it.
- If an edit or a deletion conflicts with a change made elsewhere, the app loads the latest version and asks the user to try again.
- If another tab is saving the same chat at that moment, the app asks the user to try again shortly.

## Losing the connection

When the connection to the server drops and comes back, the page catches up: the chat list, the chats kept in the browser, and their files are loaded again. If a reply stops arriving and the server is no longer working on it, the reply is marked as interrupted, and the user can retry it.

## Running several replicas

Live updates travel over the app's websocket connection. With more than one app replica, the replicas share that connection's state through Redis, so an update made on one replica reaches browsers connected to another. The Helm chart runs one replica by default, which needs neither setting.

| Env var | Default | Effect |
|-|-|-|
| `WEBSOCKET_MANAGER` | empty | Set to `redis` to share websocket state between replicas |
| `WEBSOCKET_REDIS_URL` | `REDIS_URL` | The Redis server used when `WEBSOCKET_MANAGER` is `redis` |
