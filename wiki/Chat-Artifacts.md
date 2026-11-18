# Chat Artifacts

Every saved chat has its own space for files, called its artifacts. When the model runs a skill from [[Skill Packs]], the skill reads and writes files and folders there — including nested folders, and including folders created outside the skill (for example with `create_folder`): downloaded data, processed datasets, and plots. Users browse these files next to the chat, view them, and download them, and the chat's owner can upload files of their own. Temporary chats have no artifacts.

Each chat also has an intermediate results folder, where skills leave data for the next step of a pipeline.

## What users see

The files open in a panel beside the chat. Dragging its edge resizes it, up to a little under half the window. When the window gets narrow, the panel closes the way the chat sidebar does; opening it then slides it over the chat, and clicking outside it or pressing Escape closes it. Widening the window puts it back beside the chat. On a phone the panel covers the whole screen.

The file list shows every file and folder in the chat. Some kinds of entries are recognized:

- Images, which can be viewed in place.
- HTML pages, such as interactive Plotly figures, which open in the side panel and full screen, where the user can zoom and hover. They run in a sandbox: the page cannot read the user's login or act in the chat as them. A Plotly figure saved with `include_plotlyjs='cdn'` is a few kilobytes and loads plotly.js from Plotly's CDN in the user's browser. In a reply, a markdown link to an HTML file, such as `[SST](plots/sst.html)`, opens it full screen, and image syntax, such as `![SST](plots/sst.html)`, shows it in the message.
- Zarr stores, the gridded datasets most weather skills read and write. A Zarr store is shown as one entry, not as the folders inside it.

A long name is cut short in the list; hovering over it shows the full name. The name of the open file is shown in full above the list.

Images, Zarr stores, and HTML pages (such as Plotly figures) made by skills carry their provenance: the chain of skills, versions, and arguments that produced them. The file list shows the chain of skill names under each entry; opening it shows each step's version, arguments, and inputs, so a user can see how a result was made.

## Downloading and uploading

- Users can download one file, or select several files and folders and download them as one `tar.gz` or `zip` archive. A Zarr store is downloaded as a zip of that store.
- The chat's owner can upload a single file. It replaces an existing file with the same name. Files and folders the chat server creates or uploads stay writable by skills.
- Results that code run in the browser copies back into the chat (see [[Built-in Tools]]) can only be written inside the chat's files, and lose any provenance in their images and Zarr stores.
- Dropping a file or image onto the chat bar attaches it to the next message. It appears in the bar while it is prepared. Sending the message copies it into that chat's files. The model is told the path; that line is not shown in the chat. The model does not see the contents until it asks to read that path with `read_artifact` on [[Built-in Tools]], and the user approves, unless the chat allows the agent to read files.

Archive downloads have a size limit, and so do the files copied into and out of code run in the browser on [[Built-in Tools]].

Anyone who can read a chat can list and download its files. Only the chat's owner can add or change them. Who can read a chat is described on [[Organizations]].

## Copying, sharing, and deleting chats

Cloning a chat, from the chat or from a share link, copies its files into the new chat. The new chat opens at once while its files are copied in. Until the copy is done, its file list shows **Artifact copy in progress...**, and sending a message and uploading files are blocked. When it is done, all the copied files show at once. Deleting a chat deletes its files.

Files are copied with JuiceFS's copy-on-write clone when `ARTIFACTS_DIR` is on a JuiceFS mount, which the Helm chart sets when its JuiceFS volume (`sandbox.juicefs`) is on. A chat with tens of thousands of files, such as large zarr stores, takes up to about half a minute. Where that clone is not available or fails, a small chat is copied the ordinary way and a larger chat's copy fails. A copy that runs too long also fails. A chat whose copy failed shows **Artifact copy failed, please try again** at the top of its file list.

**New chat with these artifacts**, next to **Upload** at the top of the file list, opens an empty chat that gets a copy of the chat's files and uses the same model. Anyone who can read the chat can use it; the new chat is private to them, in the same organization, like a clone, and its files are copied in the same way. With every message, the model in the new chat is told how many files it starts with, the name of the chat they came from, and every file and folder, with the skills that made the first files, and is asked to explore them before downloading anything again. When the chat has no files, the note names the chat it came from and says there are no files. The new chat opens as a chat, with the message box at the bottom and no welcome screen. Its top shows the same note, collapsed under **The chat was started with the following notes as context:**. Changes in either chat do not affect the other's files.

Each share link keeps its own copy of the chat's files as they were when the link was made. Anyone who can open the link can browse, preview, and download that copy, but no one can add to or change it, and cloning from the link copies it. See [[Share Links]].

## Settings

| Env var | Default | Effect |
|-|-|-|
| `ARTIFACTS_DIR` | `<DATA_DIR>/artifacts` | Where every chat's files are stored, one folder per chat |
