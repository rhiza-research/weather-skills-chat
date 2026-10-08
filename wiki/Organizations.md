# Organizations

An organization is a space that people share. Chats, automations, secrets, preferences, folders, skill packs, knowledge bases, models, and usage all belong to an organization. The app works in one active organization at a time, and everything a user sees and does happens in it. Users who belong to several organizations switch between them.

## Kinds of organization

| Kind | What it is | Members |
|-|-|-|
| Personal | Every user has one. It is the default active organization. | Only that user |
| Workspace | A shared organization for a team. Any verified user can create one. It stays inactive until a platform admin activates it. | Owners, admins, and users |
| Platform | One organization for the people who run the app. | Owners and admins |

Inactive organizations are hidden and cannot be used. Personal organizations and the platform organization cannot be deactivated or deleted.

## Roles

An organization member is an owner, an admin, or a user.

- Owners can do everything admins can, and are the only ones who can make someone an owner or change an owner's role.
- Admins manage members, settings, shared preferences, and shared secrets, and can turn catalog items on or off for the organization.
- Users work in the organization and use what it offers.

An organization always keeps at least one owner. Adding a person whose account is waiting for approval activates the account.

Admins and owners can change the organization's name, description, logo, and default models.

## Platform admins

A platform admin is an admin or owner of the platform organization. Platform admins activate new organizations, see every organization, set organization spending limits, manage the public catalog, and can add and remove members in any organization.

The Open WebUI admin role, including the admin settings, applies only while the platform organization is active. In any other organization, a platform admin works with the role their membership there gives them. An existing Open WebUI admin account is added to the platform organization as an admin on its next request.

## Catalog

Models, skill packs, and knowledge bases form a catalog.

- Public items are managed by platform admins in the platform organization and appear in every organization. A platform admin decides whether each one starts on or off. An organization admin can then turn it on or off for their own organization. A platform admin can also withdraw an item from every organization; it stays listed in the platform organization so it can be brought back.
- Organization items are private to one organization. Its admins can add models, skill packs, or knowledge bases only when a platform admin allows that kind for the organization. All three are off by default.

[[Skill Packs]] adds controls for single skills inside a pack.

## Sharing

Chats, automations, preferences, and folders are either private or shared with the organization. Everything in a personal organization is private.

- A chat's owner can share it with the organization. Every member can then read it. Only the owner can change it.
- If the owner makes a shared chat private, it leaves other members' chat lists. They can no longer open it.
- Cloning a chat makes a private copy for the person who cloned it, in the same organization.
- Shared chats go in the organization's team folders, and private chats in their owner's own folders.

| Env var | Default | Effect |
|-|-|-|
| `ENABLE_ADMIN_CHAT_ACCESS` | `True` | Lets platform admins, while the platform organization is active, read chats shared in any organization, including ones they do not belong to. It never opens private chats and never allows changes. |

## Deleting an organization

The owner or a platform admin can delete a workspace organization. This deletes everything in it: chats, automations and their run history, secrets, preferences, folders, skill packs, knowledge bases, models, catalog choices, and usage records.

Spending limits are described on [[Usage and Spending Caps]], and inviting people on [[Invitations]].
