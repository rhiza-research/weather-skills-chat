# Getting Help

Signed-in users report problems to the support team from inside the app, through a feedback form. The form fills in the details support needs, so the user only has to describe the problem.

## Opening the form

The form opens from:

- **Contact support** in the **?** menu at the bottom right of the chat.
- The **feedback form** link under an error in a chat. The error text is already in the description.
- A **feedback form** button in the model's reply. Every chat tells the model to offer this button when the user hits a problem the team should know about, or asks how to get help. When the problem is specific, the model can fill in a short draft of the description: what the user was trying to do, what failed, and any error text. The user can edit or replace it before sending, and nothing is sent until they do. Scheduled task runs, which have no user present, don't get this instruction. A link to the support address in a reply also opens the form.

## What is sent

The form shows what is sent along with the message: the time, the user's name and email, and a link to the open chat when there is one. The user adds a subject and a description, and sends.

The message is emailed to the support address, with the subject the user gave. Replies go to the user's email. When it is sent, the form says "Thank you for your feedback!"

## Setup

The support address is `WEBUI_HELP_EMAIL` on [[Deployment]]. The form sends with the mail settings on [[Built-in Tools]]. When those are not set, the form says the server can't send email and offers to open the message, with the same details, in the user's own email app.

Pages shown before sign-in, and to accounts waiting for approval, show the support address instead of the form.
