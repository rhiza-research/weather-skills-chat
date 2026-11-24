# Skills

A skill is a set of written instructions in markdown that the model follows in a chat, such as how to lay out a weather report. Skills have no code and run nothing. The weather skills that fetch and process data are described on [[Skill Packs]].

Skills are listed as cards at the top of the Skills page of the Workspace, above the weather skills, in the active organization (see [[Organizations]]). Any member can add a skill by writing it there or by uploading a markdown file. When the title is left blank, an uploaded file's title comes from the `name` in its frontmatter, or else from the file name.

## Private and organization skills

| Kind | Who can use it | Who can create and change it |
|-|-|-|
| Private | The user who saved it, in that organization | That user |
| Organization | Every member of the organization | The organization's admins |

Admins of a workspace or platform organization choose which kind to save. In a personal organization, every skill is private. Titles must be unique among a user's private skills, and among an organization's skills.

## Turning skills on

Each card has two switches, which only someone who can change the skill can use:

- **Enabled**: when off, the skill is not offered in chats and never reaches the model.
- **On by default**: when on, an enabled skill starts switched on in every new chat.

In a chat, the wrench button beside the message box opens the list of tools and skills. Its **Skills** section, above Weather Skills, has a switch for each enabled skill, so the user can turn skills on or off for that chat.

Skills are not offered for [[Scheduled Tasks]].

## How the model sees them

At the start of each chat turn, the app gives the model the whole markdown of every skill switched on in that chat, frontmatter included, under the skill's title. Only skills that are enabled and that the user can use in the chat's organization are included. Unlike [[Preferences]], which apply to every chat, a skill applies only to chats where it is switched on.
