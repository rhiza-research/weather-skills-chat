# Chat Artifacts

Every saved chat has its own space for files, called its artifacts. When the model runs a skill from [[Skill Packs]], the skill reads and writes files and folders there — including nested folders, and including folders created outside the skill (for example with `create_folder`): downloaded data, processed datasets, and plots. Users browse these files next to the chat, view them, and download them, and the chat's owner can upload files of their own. Temporary chats have no artifacts.

Each chat also has an intermediate results folder, where skills leave data for the next step of a pipeline.

## What users see

The file list shows every file and folder in the chat. Some kinds of entries are recognized:

- Images, which can be viewed in place.
- HTML pages, such as interactive Plotly figures, which open in the side panel and full screen, where the user can zoom and hover. They run in a sandbox: the page cannot read the user's login or act in the chat as them. A Plotly figure saved with `include_plotlyjs='cdn'` is a few kilobytes and loads plotly.js from Plotly's CDN in the user's browser. In a reply, a markdown link to an HTML file, such as `[SST](plots/sst.html)`, opens it full screen, and image syntax, such as `![SST](plots/sst.html)`, shows it in the message.
- Zarr stores, the gridded datasets most weather skills read and write. A Zarr store is shown as one entry, not as the folders inside it.

Images, Zarr stores, and HTML pages (such as Plotly figures) made by skills carry their provenance: the chain of skills, versions, and arguments that produced them. The file list shows it, so a user can see how a result was made.

## Downloading and uploading

- Users can download one file, or select several files and folders and download them as one `tar.gz` or `zip` archive. A Zarr store is downloaded as a zip of that store.
- The chat's owner can upload a single file. It replaces an existing file with the same name. Files and folders the chat server creates or uploads stay writable by skills.
- Results that code run in the browser copies back into the chat (see [[Built-in Tools]]) can only be written inside the chat's files, and lose any provenance in their images and Zarr stores.
- Dropping a file or image onto the chat bar attaches it to the next message. It appears in the bar while it is prepared. Sending the message copies it into that chat's files. The model is told the path; that line is not shown in the chat. The model does not see the contents until it asks to read that path with `read_artifact` on [[Built-in Tools]], and the user approves.

Archive downloads have a size limit, and so do the files copied into and out of code run in the browser on [[Built-in Tools]].

Anyone who can read a chat can list and download its files. Only the chat's owner can add or change them. Who can read a chat is described on [[Organizations]].

## Copying and deleting chats

Cloning a chat copies its files into the new chat. Deleting a chat deletes its files.

## Settings

| Env var | Default | Effect |
|-|-|-|
| `ARTIFACTS_DIR` | `<DATA_DIR>/artifacts` | Where every chat's files are stored, one folder per chat |
