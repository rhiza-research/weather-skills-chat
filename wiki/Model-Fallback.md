# Model Fallback

A model can have a fallback model from a second provider. When the model's own provider fails, its replies switch to the fallback without the user noticing. The reply looks the same and the model picker does not change.

## Setting up a second provider

Platform admins add the backup provider as a second OpenAI-compatible connection in the admin settings, under Connections.

- **Prefix ID**: give the backup connection a prefix, such as `requesty`. Its models are then listed as `requesty.anthropic/claude-sonnet-4-5`, so they cannot be confused with the same models on the first connection. A model ID that starts with a connection's prefix always goes to that connection.
- **Name**: optional. The model editor shows it before each model ID, as in `requesty/anthropic/claude-sonnet-4-5`. When it is empty, the connection's host is shown instead, as in `openrouter.ai/anthropic/claude-sonnet-4.5`.

The Helm chart passes only one provider key, so the backup connection's key is entered in the admin settings. See [[Deployment]].

## Choosing a model's fallback

Anyone who can edit a model sets its fallback in the model editor, under **Fallback Model**, below the base model. The list shows only models from other connections, as `connection/model-id`. A fallback from the same connection as the base model is refused when the model is saved. The base model and fallback lists are in alphabetical order, and typing in them filters the models shown.

The editor suggests a fallback by name:

- When you choose a base model.
- When you open a model that has never had a fallback setting.

It picks the model with the same name on another connection, preferring one from the same vendor. For example, it pairs `openrouter.ai/anthropic/claude-sonnet-4.5` with `requesty/anthropic/claude-sonnet-4-5`. The suggestion is only saved when you save the model, so check it first. When no other connection has a model with that name, the editor says so and leaves the fallback empty. Choose **None** for a model with no fallback.

## When replies switch

A model call switches to the fallback whenever the model's provider fails before the reply starts to appear. For example, the provider:

- cannot be reached or does not answer in time
- reports a server error
- rejects the app's API key, or the key's spending limit is used up
- reports that it is out of credits
- is rate limiting the app
- refuses the request
- starts a reply, then reports an error or drops the connection before any text or skill call arrives

A provider that fails after the reply has started to appear is not switched.

Once a reply has switched, the rest of that reply, including every skill or tool round, stays on the fallback. The next reply starts on the model's own provider again, unless that provider itself failed within the last minute. For that minute, replies for models with a fallback start on the fallback. Replies for models without a fallback keep calling the provider. A request the provider refuses as invalid, too large or for an unknown model still switches, but does not count as the provider failing.

If the fallback fails too, the call goes back to the model's own provider. If both fail, the user sees the error from the model's own provider.

## Usage

A call answered by the fallback is recorded under the same model, at the cost the fallback provider reports. See [[Usage and Spending Caps]].
