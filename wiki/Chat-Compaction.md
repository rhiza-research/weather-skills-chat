# Chat Compaction

A model can only read so much of a chat at once: its context window. Compaction lets a long chat keep going past that limit. The model summarizes the chat so far, and from then on it reads the summary in place of the earlier messages. The user still sees every message.

## Context usage

The ring in the top bar of a chat shows how full the model's context is. Clicking it shows the number of tokens used out of the model's window and the percentage. The count comes from the model provider after each reply: the tokens the model read on the reply's last model call plus the tokens it wrote. When a reply runs skills, that is its last call, not the sum of all its calls. The window size comes from the model provider's model list. A chat shows no ring until its first reply, and none for a model whose provider does not list a context window.

Right after a compaction, the count is an estimate marked **(estimate)**. The app works it out from the summary's size, before the model has read the chat again. The next reply replaces it with the provider's count.

## Compacting a chat

**Compact now**, under the count, compacts the chat up to the latest reply. It is available to anyone who can write to the chat once the reply has finished, and not on a reply that is already compacted. The summary is written by the chat's model, so it counts toward usage like any other model call (see [[Usage and Spending Caps]]).

While compaction runs:

- A line under the reply reads **Compacting conversation…**, and the ring shows a spinner.
- Sending is paused. The send button is disabled and says why, and [[Queued Messages]] wait until compaction finishes.

When it finishes, the line changes to **Chat compacted**. Clicking that line shows the summary the model now reads in place of the messages above it.

If compaction fails, or does not finish in time, the line goes away, an error is shown, and sending works again. The chat is unchanged. If someone else adds a message to the chat while it runs, that message wins and the compaction is dropped.

## Automatic compaction

The app also compacts on its own, at most once per reply:

- **After a reply** that leaves the context more than 90% full, it compacts the chat up to that reply. Sending is paused as above.
- **During a reply**, when the model's next call would not fit in its window, for example after a skill returns a large result, it compacts the chat up to the previous reply and carries on. The line appears above the user's message.

When a call still does not fit, the model is sent the reply's oldest tool results as a short note saying they were removed, starting with the oldest, until it fits. The chat keeps the full results, and the user still sees them.

## Branches

A compaction belongs to the reply it was made at. Editing or regenerating a message above that reply starts a branch without it, which the model reads in full. Messages after the reply, on any branch, use the summary.
