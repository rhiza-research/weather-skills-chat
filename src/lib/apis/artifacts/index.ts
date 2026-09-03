import { WEBUI_API_BASE_URL } from '$lib/constants';
import { parseApiError } from '$lib/apis/response';

export const getChatArtifacts = async (token: string, chatId: string) => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/chats/${chatId}/artifacts`, {
		headers: { authorization: `Bearer ${token}` }
	});
	if (!res.ok) throw await parseApiError(res);
	return res.json();
};

export const getArtifactContentUrl = (chatId: string, path: string) =>
	`${WEBUI_API_BASE_URL}/chats/${chatId}/artifacts/content?path=${encodeURIComponent(path)}`;

export const getArtifactArchiveUrl = (chatId: string, path: string) =>
	`${WEBUI_API_BASE_URL}/chats/${chatId}/artifacts/archive?path=${encodeURIComponent(path)}&format=zip`;

export const getZarrRenderUrl = (chatId: string, view: string) =>
	`${WEBUI_API_BASE_URL}/chats/${chatId}/artifacts/zarr/render?view=${encodeURIComponent(view)}`;

export const getZarrMeta = async (token: string, chatId: string, path: string) => {
	const res = await fetch(
		`${WEBUI_API_BASE_URL}/chats/${chatId}/artifacts/zarr/meta?path=${encodeURIComponent(path)}`,
		{ headers: { authorization: `Bearer ${token}` } }
	);
	if (!res.ok) throw await parseApiError(res);
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
	if (!res.ok) throw await parseApiError(res);
	return res.json();
};

export const fileFromDataUrl = async (dataUrl: string, name: string) => {
	const res = await fetch(dataUrl);
	const blob = await res.blob();
	const subtype = (blob.type.split('/')[1] || 'png').split(';')[0] || 'png';
	const filename = name.includes('.') ? name : `${name}.${subtype}`;
	return new File([blob], filename, { type: blob.type || 'application/octet-stream' });
};

export const copyFileIntoChatArtifacts = async (
	token: string,
	chatId: string | undefined | null,
	file: File
) => {
	if (!chatId || chatId === 'local') return null;
	const res = await uploadChatArtifact(token, chatId, file.name, file);
	return res?.path || file.name;
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
	if (!res.ok) throw await parseApiError(res);
	return res.json();
};

export const getArtifactArchive = async (token: string, chatId: string, paths: string[]) => {
	const qs = new URLSearchParams();
	for (const path of paths) {
		qs.append('path', path);
	}
	const res = await fetch(`${WEBUI_API_BASE_URL}/chats/${chatId}/artifacts/archive?${qs}`, {
		headers: { authorization: `Bearer ${token}` }
	});
	if (!res.ok) throw await parseApiError(res);
	return await res.arrayBuffer();
};

export const uploadArtifactArchive = async (token: string, chatId: string, data: ArrayBuffer) => {
	const form = new FormData();
	form.append('file', new Blob([data], { type: 'application/gzip' }), 'outputs.tar.gz');
	const res = await fetch(`${WEBUI_API_BASE_URL}/chats/${chatId}/artifacts/archive`, {
		method: 'POST',
		headers: { authorization: `Bearer ${token}` },
		body: form
	});
	if (!res.ok) throw await parseApiError(res);
	return res.json();
};
