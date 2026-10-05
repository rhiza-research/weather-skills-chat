# weather-skills-chat

## Wiki

`wiki/` explains what the chat app does and how it works. `.github/workflows/publish-wiki.yml` publishes it to the GitHub wiki on every push to `dev`, replacing edits made in the wiki UI.

Every PR that changes what users or admins can do, see, or configure updates `wiki/` in the same PR: add a page for a new feature, change pages whose content the PR changes, and remove what no longer exists. Read every page before deciding none is affected, since shared files such as `backend/open_webui/env.py`, `backend/open_webui/config.py`, and `backend/open_webui/utils/organizations.py` feed several pages.

What belongs on a page:

- What a feature is, what a user or admin can do with it, and how it behaves from their side.
- Roles and permissions.
- Settings an admin sets, with their default and effect. This includes a timeout or size limit when it is an admin setting.
- Deployment and platform requirements.

What stays out:

- Code-level detail: fixed byte limits, timeouts, path lists, regexes, exact error strings, HTTP status codes, internal mechanisms.
- API endpoints and request bodies. The API documents itself.
- Bugs and defects. They go in issues.
- Real third-party credential names as examples. The wiki is public. Use a placeholder such as `NAME`.

Page rules:

- A filename becomes the page title with hyphens read as spaces: `Skill-Packs.md` is the page `Skill Packs`, linked as `[[Skill Packs]]`.
- `Home.md` is the landing page. `_Sidebar.md` is the only page list; add new pages to it and remove deleted pages from it.
- When a page is removed, fix every `[[...]]` link that pointed to it.
- Current behavior only. No history.
- Each fact lives on one page; other pages link to it.