# Preferences

A preference is a saved instruction the model follows in every chat, such as "Report rainfall in millimeters". Each preference has a title and text, and belongs to one organization. Every member manages preferences on the Preferences page of the Workspace, in the active organization. In a workspace or platform organization, its admins can also choose there to save a preference for the whole organization.

The model can also list preferences and save new ones with the tools on [[Built-in Tools]]. It is told to ask the user before saving one.

## Private and organization preferences

| Kind | Applies to | Who can create and change it |
|-|-|-|
| Private | The user who saved it, in that organization | That user |
| Organization | Every member of the organization | The organization's admins |

Each preference can be turned off without deleting it. Titles must be unique among a user's private preferences, and among an organization's preferences.

## How the model sees them

At the start of every chat turn, the app gives the model all the enabled preferences that apply to the user in the active organization, sorted by title, and tells the model to follow them when they apply to the conversation. Each one is labeled as private or organization.
