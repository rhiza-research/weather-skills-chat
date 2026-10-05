# Built-in Tools

Besides the skills on [[Skill Packs]] and any Workspace tools selected for a chat, the model always has a set of built-in tools. Users do not need to select them.

## Tools the model always has

| Tool | What it lets the model do |
|-|-|
| `list_available_tools` | List the tools and skills enabled in this chat, or every tool and skill the user can use. |
| `create_automation` | Turn the current chat into a scheduled chat. See [[Automations]]. |
| `secrets_page` | Give the user a link to the page where they enter a secret. The model never receives the value. See [[Secrets]]. |
| `list_preferences` | Read the user's saved [[Preferences]]. |
| `create_preference` | Save a new preference. The model is told to ask the user first. |
| `list_artifacts` | List the chat's files. |
| `create_folder` | Create a folder in the chat's files. |
| `copy_intermediate_result` | Copy a file or folder between the chat's files and its intermediate results folder, which skills use to pass data from one step to the next. |
| `display_image` | Show an image from the chat's files in the conversation. |
| `list_email_recipients` | List the addresses the model may email. |
| `send_email` | Email a message, with files from the chat attached. |

The chat's files are described on [[Chat Artifacts]]. The file tools, `send_email`, and `create_automation` do not work in temporary chats.

## Running code

When the code interpreter is turned on for a chat, the model can also run Python with `execute_code`. The admin chooses where code runs with `CODE_INTERPRETER_ENGINE`:

- `pyodide` runs the code in the user's browser. The model can copy files and Zarr stores from the chat's files into the code's workspace before it runs, and copy results back afterward. This needs a saved chat, and copying results back needs permission to change the chat.
- `jupyter` runs the code on a Jupyter server. File copying is not available.

PNG images the code prints are shown in the conversation.

## Web search

When an admin has set up web search and a user turns it on for a chat, the model can search the web with `web_search`. The model sends one or more queries. For each query the tool runs the search, loads the top result pages, and gives the model each page's title, address, summary, and text.

The model is told to use search to support the weather analysis rather than as a general research assistant, and to tell the user what it found, where, and how it will use it. Admins can replace this guidance.

| Env var | Default | Effect |
|-|-|-|
| `ENABLE_WEB_SEARCH` | `False` | Turns web search on for the app |
| `WEB_SEARCH_ENGINE` | empty | The search engine to use; web search does not work until one is set |
| `WEB_SEARCH_RESULT_COUNT` | `3` | Result pages the model gets per query |
| `WEB_SEARCH_CONCURRENT_REQUESTS` | `10` | How many queries run at once, and how many pages are loaded per second |
| `ENABLE_WEB_LOADER_SSL_VERIFICATION` | `True` | Check the certificates of the pages loaded |
| `WEB_SEARCH_TRUST_ENV` | `False` | Load pages through the proxy configured in the server's environment |
| `WEB_SEARCH_TOOL_DESCRIPTION` | The guidance above | What the model is told about when and how to search |

## Email

The model can email the user and the people they work with. Allowed recipients are the user and every member of each active workspace or platform organization the user belongs to. The model can attach files, folders, and Zarr stores from the chat's files. Folders and Zarr stores are sent as zip files. The number and total size of attachments is limited.

Each email is sent in the user's name from the app's sender address, and replies go to the user. A footer names the user and links to a shared copy of the chat. The link uses the public address set on [[Deployment]].

The same mail settings send [[Invitations]]:

| Env var | Default | Effect |
|-|-|-|
| `EMAIL_TOOL_SMTP_HOST` | empty | Mail server |
| `EMAIL_TOOL_SMTP_PORT` | `465` | Mail server port |
| `EMAIL_TOOL_SMTP_USERNAME` | empty | Mail server login |
| `EMAIL_TOOL_SMTP_PASSWORD` | empty | Mail server password |
| `EMAIL_TOOL_SMTP_USE_TLS` | `true` | Connect with TLS from the start when true; connect plain and upgrade with STARTTLS when false |
| `EMAIL_TOOL_FROM_EMAIL` | empty | Sender address |

Email works only when the host, login, password, and sender address are all set.

How these settings are read, and when a change made in the app takes effect, is described on [[Deployment]].
