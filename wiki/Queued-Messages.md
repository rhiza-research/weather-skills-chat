# Queued Messages

A user can send their next messages while the assistant is still replying. The messages wait in a queue above the chat bar and are sent on their own, one each time a reply is done.

## Queuing a message

While a reply is running, pressing Enter, or the send button next to **Stop**, puts the message in the queue instead of sending it. The chat bar empties, so the user can keep typing.

- A chat holds up to three queued messages. Trying to queue a fourth shows an error; the queue stays as it was.
- Only text is queued. A message with attachments is not queued; the user sends it once the reply is done.
- Queued messages show above the chat bar, oldest first. Each has a delete button that removes it without sending it.

## When they are sent

The oldest queued message is sent as soon as the reply before it is done, including when the user stops that reply. It becomes the next message in the chat, as if the user had sent it then. The next one waits for that message's reply, and so on until the queue is empty.

If a reply fails, nothing more is sent. The queued messages go back into the chat bar, in order, so the user can decide what to send.

## Switching chats

The queue belongs to its chat and is kept in the browser, not on the server. It stays when the user opens another chat or reloads the page, and shows again when the user comes back. Queued messages are sent only while their chat is open: if a reply finished while the user was in another chat, the next queued message is sent when they open that chat again.

A queue in a temporary chat is dropped when the user leaves the chat. A queue does not follow the user to another browser or device.
