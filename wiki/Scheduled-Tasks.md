# Scheduled Tasks

A scheduled task sends the same prompt as a new chat on a schedule, for example a weekly rainfall summary every Monday morning. Users manage scheduled tasks on the Scheduled tasks page, opened from the sidebar. A user can also schedule a chat from its menu with **Schedule this chat**, which starts a new task with the chat's title, its requests as the prompt, its model, and its selected tools and features. In a chat, the model can also turn the current chat into a scheduled task, and list, change, or delete scheduled tasks, with the scheduled task tools on [[Built-in Tools]].

## What a scheduled task holds

- A name.
- The prompt each run sends.
- The model to use. "Default model" uses the organization's default model, or the app's default when the organization has none.
- A schedule, or no schedule for a task that only runs when someone presses Run now.
- Whether scheduled runs are on.
- The tools, skills, and chat features, such as web search, to offer the model. When no tools are chosen, the run offers every tool and skill its user can use in the organization.
- The organization it belongs to, and whether it is private or shared with the organization. Sharing is described on [[Organizations]].

Skills are kept by name, not as a particular copy of a skill. Each run uses the copy of each named skill that its user can use in the task's organization, picked the way a chat picks it on [[Skill Packs]]. Updating or reinstalling a skill pack, or adding a newer version of a skill, does not remove it from scheduled tasks. A skill that the organization no longer has is left out of the run.

When the model creates a scheduled task from a chat, it copies the chat's selected tools and features. If the model passes no prompt, the `create_scheduled_task` tool builds one from the chat's earlier user messages, leaving out the latest one. When the chat has only one user message, that message becomes the prompt. A chat with no requests yet produces no task, and the model asks the user what the task should be.

## The task page

Each scheduled task has a page with its settings above and its run history below. The **Tools** button opens the same list of tools and skills a chat uses, to turn each one on or off for the task. Web search, running code, and image generation can be turned on for the task when the user may use them in a chat. Its buttons are worded as in the chat bar. **Agent allowed to read files** lets the task's runs read the files they make, as described on [[Built-in Tools]]. With **Agent not allowed to read files**, a run cannot read them, since no one is present to approve. When a task has no tools chosen, its page starts with the tools a new chat starts with, and saving keeps that list.

People who can view a task but not change it see its settings without being able to edit them, and can still press Run now.

## In the sidebar

The sidebar has a Scheduled tasks section listing the active tasks the user can see in the active organization, one row per task, shared tasks included. A task whose scheduled runs are off is left out of the sidebar. Every task starts pinned there. A task's menu in the sidebar can unpin it, run it now, or open it for editing; a user pins it again from the Scheduled tasks page. Pinning is per user and does not change the sidebar for anyone else. The section scrolls when it holds more tasks than fit, and can be collapsed.

Tasks are sorted by most recent run by default. The sort button in the section's header sorts them by name or by newest task instead. The choice is remembered in that browser.

Clicking a task opens the chat of its latest run. A task that has never run opens its page. On the Scheduled tasks page, a task whose scheduled runs are off is greyed out.

A dot beside a task shows its latest run:

| Dot | Meaning |
|-|-|
| Pulsing grey | The run is going |
| Green | Success |
| Red | Failure |
| Orange | Unknown: the run finished without a result |
| Red ring | Error |

Opening a finished run clears its dot for that user, as does having the run's chat open when it finishes. A run that finished more than a week ago shows no dot. The dots change as runs start and finish, without reloading the page.

## Schedules

A schedule is a five-field cron expression or one of these phrases. Days of the week follow standard cron: 0 or 7 is Sunday, 1 is Monday, and 6 is Saturday.

- `hourly` or `every hour`
- `daily`, `every day`, or `everyday`, which run at midnight
- `weekly` or `every week`, which run on Sunday at midnight
- `every day at noon` or `every day at midnight`
- `every day at` a time, such as `every day at 7am` or `daily at 6:30pm`
- `weekly on` a weekday `at` a time, such as `weekly on Monday at 9am`

## What a run does

A run starts on schedule, or when someone presses Run now.

1. A scheduled run acts as the task's owner. A manual run acts as the person who pressed Run now.
2. The run checks that this person may use the model and is under the spending limits on [[Usage and Spending Caps]]. If not, no chat is created.
3. The run creates a new chat for that person in the task's organization, with the task's visibility. The chat is titled with the task's name and the date. When the task is shared, every member sees the new chat appear.
4. The prompt is sent with the task's tools and features. Skills in that run use the chat's [[Tool Runner]] when runners are on. No one is present to answer follow-up questions from the model.
5. The run is recorded with its result and a link to its chat.

A manual run opens its chat right away, so the person who pressed Run now can watch the reply arrive. Each task keeps a history of its recent runs, with their results and links to their chats.

## Run results

The model is told to report, when it finishes, whether it did what the prompt asked, with a short summary. Each run ends with one of these results:

- **Success**: the model reported that it did the task.
- **Failure**: the model reported that it could not do the task, for example because the data it needed was missing. The run itself worked.
- **Unknown**: the run finished, but the model did not report a result.
- **Error**: the run itself broke, for example because the model could not be reached or a server restart interrupted it. The error is shown with the run.

The model's summary is shown with the run, next to a success or failure.

## Picture

A scheduled task can have a picture, shown on its page, on the Scheduled tasks page, and in the sidebar. When a run reports its result, the model can choose an image the run made, such as the map it drew, and it becomes the task's picture. A run that does not choose one keeps the current picture, and so does a run that ends in an error. A task with no picture shows its first letter instead. People who can edit a task can remove its picture.

## Who can do what

- View and run a scheduled task: its owner, and every member of the organization when the task is shared.
- Edit and delete a scheduled task: its owner, and the organization's admins when the task is shared.

Deleting a scheduled task also deletes its run history and stops its schedule.
