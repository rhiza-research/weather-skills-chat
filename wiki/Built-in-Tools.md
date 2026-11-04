# Built-in Tools

Besides the skills on [[Skill Packs]] and any Workspace tools selected for a chat, the model has a set of built-in tools. Users do not need to select them.

Some built-in tools can be turned off for a chat in the Built-in group of the chat's Tools list, and for a scheduled task in the same list on its page. They are on unless turned off:

- **Email**: `list_email_recipients` and `send_email`.
- **Scheduled tasks**: the scheduled task tools. Only chats have this switch, since a scheduled task's run never gets these tools.
- **Preferences**: `list_preferences` and `create_preference`.

The others are always on, apart from those that need a chat feature such as web search or running code.

## Built-in tools

| Tool | What it lets the model do |
|-|-|
| `list_available_tools` | List the tools and skills enabled in this chat, or every tool and skill the user can use. |
| `create_scheduled_task` | Turn the current chat into a scheduled task. It copies the chat's model, skills, and switches unless the model sets them, and can set anything the task page can, such as a time limit or sharing. See [[Scheduled Tasks]]. |
| `list_scheduled_tasks` | List the scheduled tasks in the chat's organization that the user can see, with each one's schedule, model, time limit, skills, switches, sharing, last run and its result, and the start of its prompt, or show one task's whole prompt. |
| `update_scheduled_task` | Change any setting `create_scheduled_task` can set, turn the task's scheduled runs on or off, or remove its picture. |
| `delete_scheduled_task` | Delete a scheduled task and its run history. The model is told to do this only when the user asks. |
| `secrets_page` | Give the user a link to the page where they enter a secret. The model never receives the value. See [[Secrets]]. |
| `list_preferences` | Read the user's saved [[Preferences]]. |
| `create_preference` | Save a new preference. The model is told to ask the user first. |
| `list_artifacts` | List the chat's files, or one folder of them. The model can limit how many folder levels are listed, and can ask which skills produced each image, HTML page, and Zarr store. |
| `read_artifact` | Send a file from the chat's files to the model. The user approves each read in a popup, unless the user has allowed it to read files (see below). Images are sent as images; other files are searched and matching text is added to the model's context. Folders and Zarr stores cannot be read this way. |
| `create_folder` | Create a folder in the chat's files. |
| `get_tool_runner_info` | Show the chat's [[Tool Runner]]: its size and CPU and memory limits, whether it is running, the memory it uses now, how many skills are running on it, the peak memory and CPU of the most recent skill, and the other sizes the chat can use. It does not start a runner. Offered when `request_tool_runner` is. |
| `request_tool_runner` | Switch the chat's [[Tool Runner]] to another size, for example a larger one for work that ran out of memory, or back to a smaller one. Sizes that need approval ask the user first. Offered when the tool runner is on, in saved chats and scheduled task runs. See [[Tool Runner#runner-sizes]]. |
| `copy_intermediate_result` | Copy a file or folder between the chat's files and its intermediate results folder, which skills use to pass data from one step to the next. |
| `display_image` | Show an image from the chat's files in the conversation, for the user. It also shows an `.html` page, such as an interactive Plotly figure, in a sandboxed frame with a button to open it full screen. If a skill in the same turn writes that file, the display waits for the skill. To send an image to the model, use `read_artifact`; the model cannot see an HTML page. |
| `list_email_recipients` | List the addresses the model may email. |
| `send_email` | Email a message, with files from the chat attached. |

The chat's files are described on [[Chat Artifacts]]. The file tools, `send_email`, and `create_scheduled_task` do not work in temporary chats.

The scheduled task tools act as the user, so the model can change or delete only the tasks the user could change on the Scheduled tasks page. A scheduled task's run is not given these tools, so it cannot create, change, or delete scheduled tasks. Instead it has `report_task_result`, which records whether the run succeeded or failed, with a short summary and optionally an image from the chat's files for the task's picture. The results are described on [[Scheduled Tasks]].

## Reading chat files

A button in the chat bar decides whether the model may read the chat's files with `read_artifact` without asking. It is off by default and reads **Agent asks before reading files**: each read waits for the user to approve it in a popup. Turned on, it reads **Agent allowed to read files**, and the model reads files without asking. Scheduled tasks have the same switch on their page, where it reads **Agent allowed to read files** or **Agent not allowed to read files**. No one is present to approve a read during a run, so a task with Read files off cannot read its files.

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

The same mail settings send [[Invitations]] and credit requests (see [[Usage and Spending Caps]]):

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
