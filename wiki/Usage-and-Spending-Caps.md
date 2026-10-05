# Usage and Spending Caps

Weather Skills Chat records the tokens and cost of every model call, and stops new calls when an organization or a member reaches a monthly limit in US dollars.

## What is recorded

Every model call made for a chat, for an [[Automations]] run, or for the app's background tasks, such as titling a chat, is recorded with its organization, user, chat, model, tokens, and cost. The cost is the amount the model provider reports. The app does not estimate costs, so calls to a provider that reports no cost count as free.

Usage is totaled per user and per organization for each calendar month, in UTC.

## Limits

There are two limits, and a call must be under both.

- The organization limit applies to the whole organization. New personal and workspace organizations start at 300 US dollars a month. The platform organization has no limit. Only platform admins set or remove organization limits.
- The member limit applies to one person in one organization. It starts with no limit. Organization admins set it, and it cannot be higher than the organization limit.

When a limit is reached, the model stops answering new requests in that organization until the next month or until an admin raises the limit, and the user is told whether the organization or their own limit was reached. A reply that started before the limit was reached finishes. An automation run that starts while a limit is reached creates no chat.

A limit can also be set when someone is invited. See [[Invitations]].

## Seeing usage

Each user can see their own usage this month in the active organization, their remaining budget, and which limit applies to them. Members of an organization see its usage this month, and platform admins see the usage of every organization.
