import { WEBUI_API_BASE_URL } from '$lib/constants';

export const getChatArtifacts = async (token: string, chatId: string) => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/chats/${chatId}/artifacts`, {
		headers: { authorization: `Bearer ${token}` }
	});
	if (!res.ok) throw await res.json();
	return res.json();
};

export const getArtifactContentUrl = (chatId: string, path: string) =>
	`${WEBUI_API_BASE_URL}/chats/${chatId}/artifacts/content?path=${encodeURIComponent(path)}`;

export const getZarrRenderUrl = (chatId: string, view: string) =>
	`${WEBUI_API_BASE_URL}/chats/${chatId}/artifacts/zarr/render?view=${encodeURIComponent(view)}`;

export const getZarrMeta = async (token: string, chatId: string, path: string) => {
	const res = await fetch(
		`${WEBUI_API_BASE_URL}/chats/${chatId}/artifacts/zarr/meta?path=${encodeURIComponent(path)}`,
		{ headers: { authorization: `Bearer ${token}` } }
	);
	if (!res.ok) throw await res.json();
	return res.json();
};

export const createZarrView = async (token: string, chatId: string, view: object) => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/chats/${chatId}/artifacts/zarr/views`, {
		method: 'POST',
		headers: {
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify(view)
	});
	if (!res.ok) throw await res.json();
	return res.json();
};

export const uploadChatArtifact = async (
	token: string,
	chatId: string,
	path: string,
	file: File
) => {
	const form = new FormData();
	form.append('path', path);
	form.append('file', file);
	const res = await fetch(`${WEBUI_API_BASE_URL}/chats/${chatId}/artifacts`, {
		method: 'POST',
		headers: { authorization: `Bearer ${token}` },
		body: form
	});
	if (!res.ok) throw await res.json();
	return res.json();
};
