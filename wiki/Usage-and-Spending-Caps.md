# Usage and Spending Caps

Weather Skills Chat records the tokens and cost of every model call, and stops new calls when an organization or a member reaches a monthly limit in US dollars.

## What is recorded

Every model call made for a chat, for an [[Automations]] run, or for the app's background tasks, such as titling a chat, is recorded with its organization, user, chat, model, tokens, and cost. The cost is the amount the model provider reports. The app does not estimate costs, so calls to a provider that reports no cost count as free.

Usage is totaled per user and per organization for each calendar month, in UTC.

## Limits

There are two limits, and a call must be under both.

- The organization limit applies to the whole organization. New personal and workspace organizations start at 300 US dollars a month. The platform organization has no limit. Only platform admins set or remove organization limits.
- The member limit applies to one person in one organization. It starts with no limit. Organization admins set it, and it cannot be higher than the organization limit.

When a limit is reached, the model stops answering new requests in that organization until the next month or until an admin raises the limit, and the user is told whether the organization or their own limit was reached. The refused message stays in the chat with that error, so the user can retry it once the limit is raised. A reply that is still running when the limit is reached stops before its next model call, for example after a skill finishes. It keeps what it has written and the skills it has run, and shows the same message. An automation run that starts while a limit is reached creates no chat.

A limit can also be set when someone is invited. See [[Invitations]].

## Requesting more credits

When a reply stops because a limit was reached, the error in the chat has a **Request credit increase** button. It opens a short form that asks why the user needs more credits and, optionally, how many. Sending it emails the admins who can raise that limit:

- For the organization limit, the platform admins.
- For a member limit, the organization's owners and admins, or the platform admins when the organization has no admin.

A user who is one of those admins gets the email too.

The email names the user, the organization, the limit reached, and this month's spend, and links to the admin page where the limit is changed. Replies go to the user. Requests use the mail settings on [[Built-in Tools]], and cannot be sent until those are set.

## Seeing usage

The usage counter in the user menu shows the active organization's spend this month against the organization limit. A user with a member limit also sees their own spend against it. Members of an organization see its usage this month, and platform admins see the usage of every organization.
