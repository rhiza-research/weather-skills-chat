# Secrets

Many weather data services need an API key or token. Secrets store these values encrypted, so skills can use them without the value ever appearing in a chat. Users manage secrets on the Secrets page.

## Private and organization secrets

| Kind | Who can use it | Who can change or delete it |
|-|-|-|
| Private | Its owner, in one organization | Its owner |
| Organization | Every member of the organization | The organization's admins, and the member who created it |

Only organization admins can create organization secrets, and personal organizations have none. Each name can be used once among a user's private secrets and once among the organization's secrets. When a user has a private secret with the same name as an organization secret, the user's private secret is used, and the app marks the organization secret as overridden for that user.

Secret names are written like environment variable names: letters, digits, and underscores, not starting with a digit. The app never shows a stored value again; it can only be replaced.

## How skills use secrets

The model asks for secrets by name when it calls a skill. The skill receives each one as an environment variable of the same name. Names are looked up in the active organization, and if any name is missing, the skill does not run and the model is told which names are missing.

Tools can also receive a secret inside an argument, through a `{{secret:NAME}}` placeholder that the app replaces with the value before the tool runs. Placeholders work only for tools that run on the server, so values never reach the browser.

When a tool's output contains a secret value the tool was given, the app replaces the value with its placeholder.

## Asking the user for a secret

When a skill needs a secret the user has not saved, the model gives the user a link to the Secrets page with the name filled in, using the `secrets_page` tool on [[Built-in Tools]]. The user enters the value there, never in the chat.

## Encryption key

| Env var | Default | Effect |
|-|-|-|
| `SECRETS_ENCRYPTION_KEY` | empty | The key that encrypts stored secrets: a 256-bit key written as hex or base64 |

When the setting is empty, the app generates a key on first use, saves it as `<DATA_DIR>/secret_store.key`, and logs a warning. Back up that file: without it, stored secrets cannot be read. Servers that do not share a data directory each generate their own key, so when you run more than one server, set `SECRETS_ENCRYPTION_KEY` to the same value on all of them.

Deleting an organization deletes its secrets.
