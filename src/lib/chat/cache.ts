import { get } from 'svelte/store';
import { getChatById } from '$lib/apis/chats';
import { getRecentChats } from '$lib/apis/chats';
import { chatArtifactLists, chatId, socket, socketConnected } from '$lib/stores';

type Entry = {
	id: string;
	document: any;
	artifacts: any[] | null;
	revision: number;
	fresh: boolean;
	organizationId: string | null;
	touched: number;
};

const MAX_ENTRIES = 16;
const entries = new Map<string, Entry>();
const heard = new Map<string, number>();
const inflight = new Map<string, Promise<any>>();
const viewingLeaf = new Map<string, string>();
const listeners = new Set<(id: string, document: any) => void>();

let socketUp = false;
let openId = '';
let liveChatId = '';
let liveMessageId = '';
let recentOrganizationId = '';

export function revisionFrom(document: any): number {
	const value = Number(document?.meta?.revision ?? 0);
	return Number.isFinite(value) ? value : 0;
}

export function revisionOf(id: string): number | null {
	const entry = entries.get(id);
	return entry ? entry.revision : null;
}

export function setSocketUp(up: boolean) {
	socketUp = up;
	socketConnected.set(up);
	if (!up) {
		for (const entry of entries.values()) entry.fresh = false;
	}
}

export function isLive(id: string) {
	return !!id && liveChatId === id && !!liveMessageId;
}

export function beginLive(id: string, messageId: string) {
	liveChatId = id;
	liveMessageId = messageId;
}

export function endLive(messageId?: string) {
	if (!messageId || liveMessageId === messageId) {
		liveChatId = '';
		liveMessageId = '';
	}
}

export function liveMessageIdFor(id: string) {
	return isLive(id) ? liveMessageId : '';
}

export function setViewingLeaf(id: string, messageId: string) {
	if (id && messageId) viewingLeaf.set(id, messageId);
}

export function viewingLeafFor(id: string) {
	return viewingLeaf.get(id) ?? null;
}

export function onDocument(listener: (id: string, document: any) => void) {
	listeners.add(listener);
	return () => listeners.delete(listener);
}

function notify(id: string, document: any) {
	for (const listener of listeners) listener(id, document);
}

function evict() {
	if (entries.size <= MAX_ENTRIES) return;
	const ordered = [...entries.values()]
		.filter((entry) => entry.id !== openId)
		.sort((a, b) => a.touched - b.touched);
	while (entries.size > MAX_ENTRIES && ordered.length) {
		const entry = ordered.shift();
		if (!entry) break;
		entries.delete(entry.id);
	}
}

export function rememberArtifacts(id: string, files: any[]) {
	const entry = entries.get(id);
	if (entry) {
		entry.artifacts = files;
		entry.touched = Date.now();
	}
	chatArtifactLists.update((current) => ({ ...current, [id]: files }));
}

export function putChat(document: any, artifacts: any[] | null = null, allowFresh = true) {
	if (!document?.id) return null;
	const id = document.id;
	const revision = revisionFrom(document);
	const existing = entries.get(id);
	if (existing && isLive(id)) {
		const remoteHistory = document?.chat?.history || {};
		const remoteMessages = remoteHistory.messages || {};
		const localHistory = existing.document?.chat?.history || {};
		const localMessages = localHistory.messages || {};
		const remoteLive = remoteMessages[liveMessageId];
		const localLive = localMessages[liveMessageId];
		const finishedWhileAway = remoteLive?.done === true && localLive?.done !== true;
		if (!finishedWhileAway) {
			// Keep the message this tab is streaming, and take every other
			// message from the server so another tab's turn shows up.
			const messages = { ...remoteMessages, ...localMessages };
			if (localLive) messages[liveMessageId] = localLive;
			const history = {
				...remoteHistory,
				messages,
				currentId: localHistory.currentId || remoteHistory.currentId
			};
			existing.document = {
				...existing.document,
				...document,
				meta: { ...(document.meta || {}), revision },
				chat: { ...(document.chat || {}), history }
			};
			existing.revision = revision;
			existing.fresh = allowFresh && socketUp && (heard.get(id) == null || revision >= heard.get(id));
			existing.touched = Date.now();
			if (heard.get(id) == null || revision >= heard.get(id)) heard.set(id, revision);
			if (artifacts) rememberArtifacts(id, artifacts);
			return existing;
		}
		endLive(liveMessageId);
	}
	const latest = heard.get(id);
	const fresh = allowFresh && socketUp && (latest == null || revision >= latest);
	const entry: Entry = {
		id,
		document,
		artifacts: artifacts ?? existing?.artifacts ?? null,
		revision,
		fresh,
		organizationId: document.organization_id ?? null,
		touched: Date.now()
	};
	if (latest == null || revision >= latest) heard.set(id, revision);
	entries.set(id, entry);
	if (entry.artifacts) rememberArtifacts(id, entry.artifacts);
	evict();
	return entry;
}

export function rememberLocal(id: string, history: any, document?: any) {
	if (!id || id === 'local' || !history) return;
	let entry = entries.get(id);
	if (!entry && document) {
		putChat(document, null, true);
		entry = entries.get(id);
	}
	if (!entry) return;
	// A refetch may have stored a newer transcript already. The on-screen
	// history is still the older one until that document is applied, and
	// writing it back would make the stale copy look fresh.
	const localRevision = document ? revisionFrom(document) : null;
	if (!isLive(id) && localRevision != null && entry.revision > localRevision) return;
	if (!entry.document.chat) entry.document.chat = {};
	entry.document.chat.history = history;
	entry.touched = Date.now();
	if (history.currentId) viewingLeaf.set(id, history.currentId);
}

export function canPaintChat(id: string) {
	if (!socketUp) return null;
	const entry = entries.get(id);
	if (!entry?.fresh) return null;
	const latest = heard.get(id) ?? entry.revision;
	if (entry.revision !== latest) return null;
	return entry;
}

export function noteHeard(id: string, revision: number) {
	const previous = heard.get(id) ?? -1;
	if (revision > previous) heard.set(id, revision);
	const entry = entries.get(id);
	if (entry && entry.revision !== revision) entry.fresh = false;
}

export function adoptRevision(id: string, revision: number) {
	heard.set(id, revision);
	const entry = entries.get(id);
	if (!entry) return;
	entry.revision = revision;
	entry.fresh = socketUp;
	entry.document.meta = { ...(entry.document.meta || {}), revision };
}

export function dropChat(id: string) {
	entries.delete(id);
	heard.delete(id);
	viewingLeaf.delete(id);
	chatArtifactLists.update((current) => {
		const next = { ...current };
		delete next[id];
		return next;
	});
	syncWatch();
}

export function dropOrganization(organizationId: string) {
	if (!organizationId) return;
	for (const [id, entry] of [...entries.entries()]) {
		if (entry.organizationId === organizationId) {
			entries.delete(id);
			heard.delete(id);
		}
	}
	syncWatch();
}

export function setOpenChat(id: string) {
	openId = id && id !== 'local' ? id : '';
	const entry = openId ? entries.get(openId) : undefined;
	if (entry) entry.touched = Date.now();
	syncWatch();
}

export function syncWatch(live = get(socket)) {
	if (!live?.connected) return;
	const ids = [...entries.keys()];
	if (openId && !ids.includes(openId)) ids.push(openId);
	live.emit('chat:watch', {
		ids,
		active: openId || null
	});
}

export function refetchChat(token: string, id: string) {
	const pending = inflight.get(id);
	if (pending) return pending;
	const job = getChatById(token, id)
		.then((document) => {
			if (!document) return null;
			const entry = putChat(document, entries.get(id)?.artifacts ?? null, true);
			return entry?.document ?? document;
		})
		.finally(() => {
			inflight.delete(id);
		});
	inflight.set(id, job);
	job.finally(() => {
		const entry = entries.get(id);
		const latest = heard.get(id);
		if (!entry || latest == null || entry.revision >= latest) return;
		if (inflight.has(id)) return;
		refetchChat(token, id)
			.then((newer) => {
				if (newer) notify(id, newer);
			})
			.catch((error) => console.error(error));
	});
	return job;
}

export async function documentForOpen(token: string, id: string) {
	const painted = canPaintChat(id);
	if (painted) return { document: painted.document, fromMemory: true };
	if (inflight.has(id)) {
		await inflight.get(id);
		const ready = canPaintChat(id);
		if (ready) return { document: ready.document, fromMemory: true };
	}
	const document = await getChatById(token, id);
	if (document) putChat(document, entries.get(id)?.artifacts ?? null, socketUp);
	return { document, fromMemory: false };
}

export function onChatUpdated(id: string, revision: number, token: string) {
	noteHeard(id, revision);
	if (!id) return;
	if (!entries.has(id) && id !== openId) return;
	// Refetch even while this tab is streaming. putChat keeps the live
	// message and merges the other tab's messages into the cache.
	refetchChat(token, id)
		.then((document) => {
			if (document) notify(id, document);
		})
		.catch((error) => console.error(error));
}

export async function refetchWatched(token: string) {
	const ids = [...entries.keys()].filter((id) => {
		const entry = entries.get(id);
		return !!entry && !entry.fresh;
	});
	const queue = [...ids];
	const worker = async () => {
		while (queue.length) {
			const id = queue.shift();
			if (!id) return;
			try {
				const document = await refetchChat(token, id);
				if (document && id === get(chatId)) notify(id, document);
			} catch (error) {
				console.error(error);
			}
		}
	};
	await Promise.all([worker(), worker()]);
}

export async function preloadRecent(token: string, organizationId: string) {
	if (!organizationId) return;
	recentOrganizationId = organizationId;
	try {
		const rows = await getRecentChats(token);
		if (!Array.isArray(rows)) return;
		for (const row of rows) {
			const document = row?.chat;
			if (!document?.id) continue;
			const existing = entries.get(document.id);
			const incoming = revisionFrom(document);
			if (
				document.id === openId &&
				existing &&
				(isLive(document.id) || existing.revision >= incoming)
			) {
				if (Array.isArray(row.artifacts)) rememberArtifacts(document.id, row.artifacts);
				continue;
			}
			const entry = putChat(document, row.artifacts ?? [], true);
			if (document.id === openId && entry?.document) notify(document.id, entry.document);
		}
		syncWatch();
	} catch (error) {
		console.error(error);
	}
}

/** Re-pull the recent window after the socket drops and reconnects. */
export async function refreshRecent(token: string) {
	if (!token || !recentOrganizationId) return;
	await preloadRecent(token, recentOrganizationId);
}

export function cachedArtifacts(id: string) {
	return entries.get(id)?.artifacts ?? null;
}
