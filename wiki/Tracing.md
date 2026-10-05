# Tracing

Weather Skills Chat can send a trace of every chat to Langfuse, so admins can see what the model was asked, which tools it ran, what they returned, and how many tokens each step used. A tracing problem never stops a chat.

## What a trace shows

Each chat request, from a user or from an [[Automations]] run, becomes one trace. The trace is tagged with the user, the chat, the model, the tools offered, and whether it came from a chat or an automation. Inside it are:

- Each model call, with the messages sent, the tools offered, the model's reply, and token usage. When a connection hands its model calls to OpenRouter, OpenRouter's record of each call appears here in place of the app's. See below.
- Each tool run, with its input and output.

Very long inputs and outputs are shortened.

Traces sent to Langfuse include the user's email address, and the contents of the chat's messages, tool inputs, and tool outputs.

## Model calls recorded by OpenRouter

Each OpenAI-compatible connection in the admin settings has a Model-call tracing setting.

- App, the default, has the app record the connection's model calls in the trace.
- OpenRouter Broadcast hands recording to OpenRouter. The app records no model call for the connection, and sends OpenRouter what it needs to place its own record inside the chat's trace. OpenRouter's record shows the model that answered and the cost OpenRouter charged. When the app cannot send a call, or OpenRouter answers with an error, the app records that failure in the trace.

While tracing is on, the app sends OpenRouter the user's email address and the chat's identifier with every model call on a connection set to OpenRouter Broadcast. While tracing is off, it sends neither.

OpenRouter Broadcast records calls only when Broadcast to the same Langfuse project is set up in OpenRouter:

1. In Langfuse, create an API key pair for the project.
2. In OpenRouter, turn on Broadcast in the observability settings, add Langfuse as a destination with that key pair, and test the connection.
3. Limit the Langfuse destination to the OpenRouter API keys the connection uses. OpenRouter records every request made with a key Broadcast covers, so every connection that uses those keys must be set to OpenRouter Broadcast, or its calls are recorded twice.
4. In the admin settings, edit the connection and set Model-call tracing to OpenRouter Broadcast.

## Settings

| Env var | Default | Effect |
|-|-|-|
| `LANGFUSE_PUBLIC_KEY` | empty | Langfuse public key |
| `LANGFUSE_SECRET_KEY` | empty | Langfuse secret key |
| `LANGFUSE_BASE_URL` | not set | Address of the Langfuse server |
| `LANGFUSE_HOST` | not set | Address of the Langfuse server, used when `LANGFUSE_BASE_URL` is not set |
| `LANGFUSE_ENABLED` | not set | Turns tracing on or off |
| `LANGFUSE_TRACING_ENABLED` | not set | Turns tracing on or off when `LANGFUSE_ENABLED` is not set |
| `LANGFUSE_TRACING_ENVIRONMENT` | `default` | The Langfuse environment traces are filed under, including the model calls OpenRouter records |

When neither address is set, traces go to Langfuse Cloud at `https://cloud.langfuse.com`.

Tracing needs both keys. With both keys set and no on or off switch, tracing is on. When a switch is set, tracing is on only if it is `true`.

The Helm chart always sets `LANGFUSE_ENABLED`, so in a chart deployment tracing is on only when the chart turns it on. See [[Deployment]].
