# Automations

An automation sends the same prompt as a new chat on a schedule, for example a weekly rainfall summary every Monday morning. Users manage automations on the Automations page. The model can also turn the current chat into an automation with the `create_automation` tool on [[Built-in Tools]].

## What an automation holds

- A name.
- The prompt each run sends.
- The model to use.
- A schedule, or no schedule for an automation that only runs when someone presses Run.
- Whether scheduled runs are enabled.
- The tools, skills, and chat features, such as web search, to offer the model. When no tools are chosen, the run offers every tool and skill its user can use in the organization.
- The organization it belongs to, and whether it is private or shared with the organization. Sharing is described on [[Organizations]].

When the model creates an automation from a chat, it copies the chat's selected tools and features. If the model passes no prompt, the `create_automation` tool builds one from the chat's earlier user messages, leaving out the latest one. When the chat has only one user message, that message becomes the prompt. A chat with no requests yet produces no automation, and the model asks the user what the task should be.

## Schedules

A schedule is a five-field cron expression or one of these phrases:

- `hourly` or `every hour`
- `daily`, `every day`, or `everyday`, which run at midnight
- `weekly` or `every week`, which run once a week at midnight
- `every day at noon` or `every day at midnight`
- `every day at` a time, such as `every day at 7am` or `daily at 6:30pm`
- `weekly on` a weekday `at` a time, such as `weekly on Monday at 9am`

## What a run does

A run starts on schedule, or when someone presses Run.

1. A scheduled run acts as the automation's owner. A manual run acts as the person who pressed Run.
2. The run checks that this person may use the model and is under the spending limits on [[Usage and Spending Caps]]. If not, no chat is created.
3. The run creates a new chat for that person in the automation's organization, with the automation's visibility. The chat is titled with the automation's name and the date. When the automation is shared, every member sees the new chat appear.
4. The prompt is sent with the automation's tools and features. No one is present to answer follow-up questions from the model.
5. The run is recorded with its outcome and a link to its chat.

A manual run opens its chat right away, so the person who pressed Run can watch the reply arrive. Each automation keeps a history of its recent runs, with links to their chats.

## Who can do what

- View and run an automation: its owner, and every member of the organization when the automation is shared.
- Edit and delete an automation: its owner, and the organization's admins when the automation is shared.

Deleting an automation also deletes its run history and stops its schedule.
