# Long Chats

Every model has a limit on how much of a chat it can read at once. A long chat, especially one where skills have run many times, can grow past that limit, and the model provider then refuses the request.

To keep long chats working, the app checks the size of a chat before each model call. When the chat is over the context budget, the app leaves part of it out of what it sends to the model, oldest first:

1. Output from older tool calls is replaced with a short note saying it was cleared. The model still sees which tools it called and with what inputs, and can run a tool again if it needs the output.
2. If that is not enough, whole older exchanges, each a user message and the replies to it, are left out.

The latest message and the last few rounds of tool calls are always sent in full, and so are the model's instructions.

Nothing is deleted. The chat keeps every message and tool output, and everything stays on screen; only the model's view of the chat is shorter. A reply written from a shortened view shows a note under it saying so.

So in a long chat the model may not remember the details of tool output from much earlier. Asking it to run the tool again gives it the output again, and a new chat starts with nothing left out.

This applies to every model call: chats, each round of tool calls, [[Scheduled Tasks]] runs, and calls sent to a model's backup (see [[Model Fallback]]).

## Settings

| Env var | Default | Effect |
|-|-|-|
| `MODEL_CONTEXT_TOKEN_BUDGET` | `800000` | Most tokens, as the app estimates them, sent to a model in one call. One budget applies to every model, so set it below the smallest context window among the models in use. `0` turns trimming off. |
