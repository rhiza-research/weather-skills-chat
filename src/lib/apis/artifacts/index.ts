import { WEBUI_API_BASE_URL } from '$lib/constants';
import { parseApiError } from '$lib/apis/response';
import { rememberArtifacts } from '$lib/chat/cache';

export const getChatArtifacts = async (token: string, chatId: string) => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/chats/${chatId}/artifacts`, {
		headers: { authorization: `Bearer ${token}` }
	});
	if (!res.ok) throw await parseApiError(res);
	return res.json();
};

// Joins the artifact-list request started when a chat load begins. Not a cache:
// the panel consumes it once, and later polls fetch again.
let artifactListInflight: { chatId: string; promise: Promise<unknown> } | null = null;

export const prefetchChatArtifacts = (token: string, chatId: string) => {
	const promise = getChatArtifacts(token, chatId).then((files) => {
		if (Array.isArray(files)) rememberArtifacts(chatId, files);
		return files;
	});
	artifactListInflight = { chatId, promise };
	promise.catch(() => {
		if (artifactListInflight?.promise === promise) {
			artifactListInflight = null;
		}
	});
	return promise;
};

export const takePrefetchedChatArtifacts = (chatId: string) => {
	if (artifactListInflight?.chatId !== chatId) return null;
	const promise = artifactListInflight.promise;
	artifactListInflight = null;
	return promise;
};

export const getArtifactContentUrl = (chatId: string, path: string) =>
	`${WEBUI_API_BASE_URL}/chats/${chatId}/artifacts/content?path=${encodeURIComponent(path)}`;

/** Relative markdown hrefs point at this chat's sandbox. Absolute URLs do not. */
export const artifactHrefForChat = (href: string, chatId: string | null | undefined) => {
	if (!chatId || chatId === 'local') return null;
	let raw = (href || '').trim();
	if (
		!raw ||
		raw.startsWith('#') ||
		raw.startsWith('/') ||
		raw.startsWith('//') ||
		/^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(raw)
	) {
		return null;
	}
	raw = raw.split('#')[0].split('?')[0];
	try {
		raw = decodeURIComponent(raw);
	} catch {
		return null;
	}
	raw = raw.replace(/^\.\//, '').replace(/\\/g, '/');
	if (!raw || raw === '.') return null;
	if (raw.split('/').some((part) => part === '' || part === '..')) return null;
	return getArtifactContentUrl(chatId, raw);
};

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
