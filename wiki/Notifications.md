# Notifications

When a chat reply finishes, Weather Skills can play a short sound and show an in-app notice. The sound plays if the user is looking at a different chat, or if this browser tab is in the background. It does not play while the user is focused on the chat that just finished.

When the model waits for the user to answer a popup, such as approving a file read (see [[Built-in Tools]]), and the user is in a different chat or this browser tab is in the background, Weather Skills shows a notice with a different sound. Clicking the notice opens that chat, where the popup is waiting. A popup no one answers soon enough lapses, and the model is told it could not ask.

Users can turn both sounds off under Settings → Interface. Desktop system notifications, for finished replies and for popups, are a separate setting under Settings → General, and are off by default.
