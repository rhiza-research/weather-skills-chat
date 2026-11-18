# Share Links

A share link gives a read-only view of a chat as it was when the link was made: its messages and a copy of its files. Anyone who has the link can open it until it expires, with or without an account or signing in. On the shared page they can read the messages and browse, preview, and download the files. Cloning the chat to continue it needs a sign-in; someone who is not signed in is asked to sign in first and then comes back to the link. Where a clone goes is described on [[Organizations]].

## Creating a link

Only a chat's owner can share it. To share a chat someone else owns, clone it and share the copy. Choosing **Share** from the chat's menu opens a dialog with an expiry, in days, that defaults to 7 and can be set from 1 to 365. **Create share link** makes the link and copies it to the clipboard. The dialog stays open, and while the link is being made a greyed-out row with a spinner stands in for it.

The dialog lists every link to the chat that has not expired, newest first, with when it was made and when it expires. Each row has a button that copies that link again and one that deletes it.

Each link is separate. Creating another link makes a new one with the chat as it is then. Earlier links keep showing what they showed when they were made, each until its own expiry. Messages and files added to the chat after a link is made never reach that link.

## Expiry and removal

When a link expires it stops working, and the app deletes its copy of the chat and files within about an hour. Deleting a link from the dialog stops it working at once and deletes its copy; the chat's other links keep working. Opening an expired or removed link shows a message saying so and goes to the home page. Links made before share links had an expiry do not expire.

Deleting a chat deletes all of its links and their copies.

## Links in emails

Each email sent with the email tool makes a new link that expires after 7 days. The footer shows the link and its expiry date. See [[Built-in Tools]].
