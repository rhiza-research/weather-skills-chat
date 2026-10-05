# Tracing

Weather Skills Chat can send a trace of every chat to Langfuse, so admins can see what the model was asked, which tools it ran, what they returned, and how many tokens each step used. A tracing problem never stops a chat.

## What a trace shows

Each chat request, from a user or from an [[Automations]] run, becomes one trace. The trace is tagged with the user, the chat, the model, the tools offered, and whether it came from a chat or an automation. Inside it are:

- Each model call, with the messages sent, the tools offered, the model's reply, and token usage.
- Each tool run, with its input and output.

Very long inputs and outputs are shortened.

Traces sent to Langfuse include the user's email address, and the contents of the chat's messages, tool inputs, and tool outputs.

## Settings

| Env var | Default | Effect |
|-|-|-|
| `LANGFUSE_PUBLIC_KEY` | empty | Langfuse public key |
| `LANGFUSE_SECRET_KEY` | empty | Langfuse secret key |
| `LANGFUSE_BASE_URL` | not set | Address of the Langfuse server |
| `LANGFUSE_HOST` | not set | Address of the Langfuse server, used when `LANGFUSE_BASE_URL` is not set |

When neither address is set, traces go to Langfuse Cloud at `https://cloud.langfuse.com`.
| `LANGFUSE_ENABLED` | not set | Turns tracing on or off |
| `LANGFUSE_TRACING_ENABLED` | not set | Turns tracing on or off when `LANGFUSE_ENABLED` is not set |

Tracing needs both keys. With both keys set and no on or off switch, tracing is on. When a switch is set, tracing is on only if it is `true`.

The Helm chart always sets `LANGFUSE_ENABLED`, so in a chart deployment tracing is on only when the chart turns it on. See [[Deployment]].
