# Signing In and Out

Each time a person signs in on a browser or device, that sign-in lasts a set time and then asks them to sign in again. Signing in with a password, with Google or another provider, or by accepting an invitation ([[Invitations]]) all work the same way.

## How long a sign-in lasts

A sign-in ends after the time set by the admin, 30 days by default and never more than 90 days. Using the app does not extend it. The person is then sent to the sign-in page, and after signing in they return to the page they were on. Sign-ins made before sign-ins had a time limit do not end on their own; signing out everywhere or changing the password ends them.

## Signing out

**Sign Out** in the user menu signs out of the current browser only. Other browsers and devices stay signed in.

**Sign out everywhere**, in Settings under Account, ends every sign-in to the account, including the current one. The current browser goes to the sign-in page at once; other browsers and devices go there on their next action. Use it after losing a device or if someone else may have access to the account.

Changing the password in Settings signs out every other browser and device; the current one stays signed in. When an admin sets a user's password from the users list in the admin panel, that user is signed out everywhere.

Signing out of the app does not sign a person out of Google or another sign-in provider. If they are still signed in there, signing back in to the app takes one click.

API keys are not sign-ins. Signing out everywhere and changing the password leave them working.

## Settings

| Env var | Default | Effect |
|-|-|-|
| `JWT_EXPIRES_IN` | `30d` | How long a sign-in lasts, as a number and unit (`s`, `m`, `h`, `d`, `w`). Values over 90 days, and `-1`, mean 90 days. Also set in the admin settings under General as **JWT Expiration**; a value saved there replaces the env var. A change applies to sign-ins made after it. |
