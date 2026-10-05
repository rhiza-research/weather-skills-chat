# Chat Artifacts

Every saved chat has its own space for files, called its artifacts. When the model runs a skill from [[Skill Packs]], the skill reads and writes files there: downloaded data, processed datasets, and plots. Users browse these files next to the chat, view them, and download them, and the chat's owner can upload files of their own. Temporary chats have no artifacts.

Each chat also has an intermediate results folder, where skills leave data for the next step of a pipeline.

## What users see

The file list shows every file and folder in the chat. Some kinds of entries are recognized:

- Images, which can be viewed in place.
- Zarr stores, the gridded datasets most weather skills read and write. A Zarr store is shown as one entry, not as the folders inside it.
- Zarr views, which draw a Zarr store as an image. See below.

Images and Zarr stores made by skills carry their provenance: the chain of skills, versions, and arguments that produced them. The file list shows it, so a user can see how a result was made.

## Downloading and uploading

- Users can download one file, or select several files and folders and download them as one `tar.gz` or `zip` archive. Zarr stores are downloaded whole.
- The chat's owner can upload a single file, or a tar archive that is unpacked into the chat's files. Uploaded files replace existing files with the same name. An archive that tries to write outside the chat's files is refused.
- When a tar archive is unpacked into the chat, provenance is removed from the images and Zarr stores in it.

Archive downloads and archive uploads have a size limit, and so do the files the model copies into running code on [[Built-in Tools]].

Anyone who can read a chat can list and download its files. Only the chat's owner can add or change them. Who can read a chat is described on [[Organizations]].

## Zarr views

A Zarr view is a saved way of drawing a Zarr store. It names the store, a title, the variable to draw, and the style: a map (heatmap) or a time series. It can also set the color scale, pick one position along dimensions such as time, and limit the map to a latitude and longitude box. Opening a view draws the image from the current data.

A view is a small JSON file in the chat's files, usually with a name ending in `.zarrview.json`. Anything that writes files into the chat, such as a skill, can create one. The model has no built-in tool for creating views, and the file list only shows and opens them.

## Copying and deleting chats

Cloning a chat copies its files into the new chat. Deleting a chat deletes its files.

## Settings

| Env var | Default | Effect |
|-|-|-|
| `ARTIFACTS_DIR` | `<DATA_DIR>/artifacts` | Where every chat's files are stored, one folder per chat |
