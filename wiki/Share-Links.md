# Share Links

A share link gives a read-only view of a chat as it was when the link was made: its messages and a copy of its files. Anyone signed in to the app who has the link can open it until it expires. On the shared page they can read the messages, browse, preview, and download the files, and clone the chat to continue it. Where a clone goes is described on [[Organizations]].

## Creating a link

Only a chat's owner can share it. To share a chat someone else owns, clone it and share the copy. Choosing **Share** from the chat's menu opens a dialog with an expiry, in days, that defaults to 7 and can be set from 1 to 365. **Create share link** makes the link and copies it to the clipboard. The dialog stays open, and while the link is being made a greyed-out row with a spinner stands in for it.

The dialog lists every link to the chat that has not expired, newest first, with when it was made and when it expires. Each row has a button that copies that link again.

Each link is separate. Creating another link makes a new one with the chat as it is then. Earlier links keep showing what they showed when they were made, each until its own expiry. Messages and files added to the chat after a link is made never reach that link.

## Expiry and removal

When a link expires it stops working, and the app deletes its copy of the chat and files within about an hour. Opening an expired or removed link shows a message saying so and goes to the home page. Links made before share links had an expiry do not expire.

Deleting a chat deletes all of its links and their copies.

## Links in emails

Each email sent with the email tool makes a new link that expires after 7 days. The footer shows the link and its expiry date. See [[Built-in Tools]].
