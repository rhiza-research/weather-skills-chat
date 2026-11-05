# Requesting Access

A person without an account asks for one from the sign-in page. A platform admin approves the request before the person can use the app. Admins can also bring people in directly with [[Invitations]].

## Sending a request

**Request access** under the sign-in form opens the request form. It asks for a name, an email address, a few words on who the person is and why they want access, and a password. Sign-in with Google, Microsoft, GitHub, or single sign-on is offered on the sign-in form only.

After sending, the form is replaced by a confirmation that the person will get an email once their access is approved, with a button back to the sign-in form. Sending a request does not sign the person in. Signing in before approval shows a page saying the account is waiting for activation.

Each platform admin gets an email with the person's name, email address, and description. The emails need the mail settings on [[Built-in Tools]].

## Approving a request

A platform admin (see [[Organizations]]) activates the account as a user from the users list in the admin panel. The person then gets an email saying their access is approved. Adding the person to an organization, or accepting a platform invitation, also activates the account, without that email.

## Settings

| Env var | Default | Effect |
|-|-|-|
| `ENABLE_SIGNUP` | `True` | Shows **Request access** on the sign-in page. Also set in the admin settings. |
| `DEFAULT_USER_ROLE` | `pending` | Role of a new account. With `user`, a request signs the person in at once, with no approval. Also set in the admin settings. |
