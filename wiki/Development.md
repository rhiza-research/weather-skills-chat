# Development

This page covers running Weather Skills Chat from a source checkout. Which branch pull requests target, and how changes reach staging and production, is described under the release model on [[Deployment]].

## Requirements

- Node.js 18.13 through 22.x, and npm.
- Python 3.11 or 3.12, with the packages in `backend/requirements.txt`.
- `git` and `uv` on `PATH`, for [[Skill Packs]].

## Running the app

Start the frontend and the backend in two terminals.

- Frontend: `npm run dev` from the repository root. It starts a development server that sends its API calls to port 8080 on the same host.
- Backend: `./dev.sh` from the `backend` directory. It serves the API on port 8080, or on `PORT` when set, and reloads when code changes.

Without `DATA_DIR`, the backend keeps its data in `backend/data`. In development mode the backend also serves interactive API documentation at `/docs`.

Skill confinement needs Linux Landlock. On a machine without it, such as a Mac, turn confinement off with its setting on [[Skill Packs]] so skills can run in chats.

## Skill smoke test

`scripts/smoke_skills.py` checks the whole skill pipeline against the configured database and folders: it installs a small test skill pack, checks the tool made from it, runs the skill in a test chat, and checks that bad secret names and non-https pack addresses are refused. It prints `ALL-SMOKE-OK` when every check passes. The test pack, its tool, and the test chat's files are left in place afterward.
