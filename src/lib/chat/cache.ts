import { get } from 'svelte/store';
import { applyChatHistoryPatch, getChatById, getRecentChats } from '$lib/apis/chats';
import { WEBUI_API_BASE_URL, WEBUI_BASE_URL } from '$lib/constants';
import { markUnseenMessages } from '$lib/chat/scroll';
import { chatArtifactLists, chatId, socket, socketConnected } from '$lib/stores';
import {
	GENERATION_LOST_MESSAGE,
	clearSpinningToolCalls
} from '$lib/utils/generationLiveness';
import { accumulateUsage } from '$lib/utils/usage';

type Entry = {
	id: string;
	document: any;
	artifacts: any[] | null;
	revision: number;
	/** A newer revision arrived while this chat was streaming. */
	later?: number;
	organizationId: string | null;
	touched: number;
};

const MAX_ENTRIES = 16;
const entries = new Map<string, Entry>();
const inflight = new Map<string, Promise<any>>();
const viewingLeaf = new Map<string, string>();
const listeners = new Set<(id: string, document: any) => void>();
const lostListeners = new Set<(id: string) => void>();
const openTranscriptListeners = new Set<(event: any) => void>();

/** No socket activity for this long, and no task row, means the turn died. */
const TURN_SILENCE_MS = 30_000;
const TURN_CHECK_MS = 5_000;

let openId = '';
const liveTurns = new Map<string, string>();
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
	socketConnected.set(up);
}

export function isLive(id: string) {
	return !!id && liveTurns.has(id);
}

export function beginLive(id: string, messageId: string) {
	if (!id || !messageId) return;
	liveTurns.set(id, messageId);
	armTurnWatch(id, messageId);
}

export function endLive(messageId?: string) {
	const ended: string[] = [];
	if (!messageId) {
		for (const id of [...liveTurns.keys()]) {
			disarmTurnWatch(id);
			ended.push(id);
		}
		liveTurns.clear();
	} else {
		for (const [id, liveId] of liveTurns) {
			if (liveId === messageId) {
				liveTurns.delete(id);
				disarmTurnWatch(id);
				ended.push(id);
			}
		}
	}
	for (const id of ended) catchUp(id);
}

export function onTurnLost(listener: (id: string) => void) {
	lostListeners.add(listener);
	return () => lostListeners.delete(listener);
}

/** Fired after the open chat's transcript object is updated. Paint only. */
export function onOpenTranscript(listener: (event: any) => void) {
	openTranscriptListeners.add(listener);
	return () => openTranscriptListeners.delete(listener);
}

type TurnWatch = {
	messageId: string;
	lastActivity: number;
	timer: ReturnType<typeof setInterval> | null;
	checking: boolean;
};

const turnWatches = new Map<string, TurnWatch>();

function armTurnWatch(id: string, messageId: string) {
	disarmTurnWatch(id);
	if (typeof window === 'undefined') return;
	const watch: TurnWatch = {
		messageId,
		lastActivity: Date.now(),
		timer: null,
		checking: false
	};
	watch.timer = setInterval(() => {
		void checkTurnWatch(id);
	}, TURN_CHECK_MS);
	turnWatches.set(id, watch);
}

function disarmTurnWatch(id: string) {
	const watch = turnWatches.get(id);
	if (!watch) return;
	if (watch.timer) clearInterval(watch.timer);
	turnWatches.delete(id);
}

function noteTurnActivity(id: string) {
	const watch = turnWatches.get(id);
	if (!watch) return;
	watch.lastActivity = Date.now();
}

async function taskIdsFor(token: string, id: string): Promise<string[]> {
	const res = await fetch(`${WEBUI_BASE_URL}/api/tasks/chat/${id}`, {
		headers: {
			Accept: 'application/json',
			...(token && { authorization: `Bearer ${token}` })
		}
	});
	if (!res.ok) return [];
	const body = await res.json();
	return Array.isArray(body?.task_ids) ? body.task_ids : [];
}

function cachedMessage(id: string, messageId: string) {
	return entries.get(id)?.document?.chat?.history?.messages?.[messageId] ?? null;
}

function publish(id: string) {
	const document = entries.get(id)?.document;
	if (document && id === get(chatId)) notify(id, document);
}

async function stampTurnLost(id: string, messageId: string, token: string) {
	const watch = turnWatches.get(id);
	if (watch) watch.checking = true;
	try {
		const message = cachedMessage(id, messageId);
		if (!message || message.done === true) {
			disarmTurnWatch(id);
			return;
		}
		const document = await refetchChat(token, id).catch(() => null);
		const stored = document?.chat?.history?.messages?.[messageId];
		if (stored?.done === true) {
			endLive(messageId);
			publish(id);
			return;
		}
		const current = cachedMessage(id, messageId);
		if (!current || current.done === true) {
			disarmTurnWatch(id);
			return;
		}
		current.error = current.error ?? { content: GENERATION_LOST_MESSAGE };
		current.done = true;
		current.content = clearSpinningToolCalls(current.content ?? '');
		endLive(messageId);
		publish(id);
		for (const listener of lostListeners) listener(id);
		await applyChatHistoryPatch(token, id, {
			upsert: { [messageId]: current },
			expected_revision: revisionOf(id)
		}).catch(async (error) => {
			if (error?.status !== 409) return;
			const latest = await refetchChat(token, id).catch(() => null);
			const finished = latest?.chat?.history?.messages?.[messageId];
			if (finished?.done === true && !finished?.error) publish(id);
		});
	} finally {
		const still = turnWatches.get(id);
		if (still) still.checking = false;
	}
}

async function checkTurnWatch(id: string) {
	const watch = turnWatches.get(id);
	if (!watch || watch.checking) return;
	const message = cachedMessage(id, watch.messageId);
	if (!message || message.done === true) {
		disarmTurnWatch(id);
		return;
	}
	if (Date.now() - watch.lastActivity < TURN_SILENCE_MS) return;
	watch.checking = true;
	try {
		const token = localStorage.token;
		if (!token) return;
		const tasks = await taskIdsFor(token, id).catch(() => []);
		const again = turnWatches.get(id);
		if (!again || again.messageId !== watch.messageId) return;
		if (cachedMessage(id, watch.messageId)?.done === true) {
			disarmTurnWatch(id);
			return;
		}
		if (tasks.length) {
			again.lastActivity = Date.now();
			return;
		}
		await stampTurnLost(id, watch.messageId, token);
	} finally {
		const again = turnWatches.get(id);
		if (again) again.checking = false;
	}
}

/**
 * Opening a chat uses the same rules as one already on screen.
 * A turn this tab already started keeps its watch: the task row can lag
 * the send, and treating that gap as a dead connection downloads the chat
 * and stamps it lost. A live task arms the watch. Only an unfinished
 * message with no task and no watch is checked against the server.
 */
export async function settleLoadedTurn(id: string, token: string, hasLiveTask: boolean) {
	if (isLive(id)) return;
	const messages = entries.get(id)?.document?.chat?.history?.messages || {};
	const unfinished = Object.values(messages).filter(
		(message: any) => message?.role === 'assistant' && message.done !== true && message?.id
	) as { id: string }[];
	if (!unfinished.length) return;
	if (hasLiveTask) {
		beginLive(id, unfinished[unfinished.length - 1].id);
		return;
	}
	for (const message of unfinished) {
		await stampTurnLost(id, message.id, token);
	}
}

export function liveMessageIdFor(id: string) {
	return liveTurns.get(id) ?? '';
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
		.filter((entry) => entry.id !== openId && !isLive(entry.id))
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

export function putChat(document: any, artifacts: any[] | null = null) {
	if (!document?.id) return null;
	const id = document.id;
	const revision = revisionFrom(document);
	const existing = entries.get(id);
	if (existing?.document?.chat?.history) {
		// One history object for the life of the entry. The screen renders it.
		const history = existing.document.chat.history;
		const messages = history.messages || (history.messages = {});
		const remoteMessages = document?.chat?.history?.messages || {};
		const liveId = liveMessageIdFor(id);
		const localLive = messages[liveId];
		const remoteLive = remoteMessages[liveId];
		if (revision >= existing.revision) {
			existing.revision = revision;
			existing.document.meta = { ...(document.meta || {}), revision };
		}
		if (remoteLive?.done === true && localLive?.done !== true) {
			messages[liveId] = remoteLive;
			endLive(liveId);
		}
		for (const [messageId, remote] of Object.entries(remoteMessages)) {
			if (messageId === liveId && messages[liveId]?.done !== true) continue;
			messages[messageId] = remote;
		}
		if (localLive && messages[liveId]?.done !== true) messages[liveId] = localLive;
		if (!isLive(id) && id !== openId && document?.chat?.history?.currentId) {
			history.currentId = document.chat.history.currentId;
		} else if (!history.currentId) {
			history.currentId = document?.chat?.history?.currentId || history.currentId;
		}
		if (document.title) existing.document.title = document.title;
		if (document.chat?.title && existing.document.chat) {
			existing.document.chat.title = document.chat.title;
		}
		existing.touched = Date.now();
		if (artifacts) rememberArtifacts(id, artifacts);
		return existing;
	}
	const entry: Entry = {
		id,
		document,
		artifacts: artifacts ?? existing?.artifacts ?? null,
		revision,
		organizationId: document.organization_id ?? null,
		touched: Date.now()
	};
	entries.set(id, entry);
	if (entry.artifacts) rememberArtifacts(id, entry.artifacts);
	evict();
	return entry;
}

/** Point the screen at the cache history, keeping optimistic messages. */
export function holdHistory(id: string, local: any) {
	const history = entries.get(id)?.document?.chat?.history;
	if (!history || history === local || !local?.messages) return history ?? null;
	if (!history.messages) history.messages = {};
	for (const [messageId, message] of Object.entries(local.messages)) {
		if (!history.messages[messageId]) history.messages[messageId] = message;
	}
	if (local.currentId) history.currentId = local.currentId;
	return history;
}

function hasDocument(id: string) {
	return !!entries.get(id)?.document;
}

function artifactListFor(id: string): any[] | null {
	const entry = entries.get(id);
	if (Array.isArray(entry?.artifacts)) return entry.artifacts;
	const listed = get(chatArtifactLists)[id];
	return Array.isArray(listed) ? listed : null;
}

function setRevision(id: string, revision: number) {
	const entry = entries.get(id);
	if (!entry || !Number.isFinite(revision) || revision < entry.revision) return;
	entry.revision = revision;
	if (entry.document) entry.document.meta = { ...(entry.document.meta || {}), revision };
	if (entry.later != null && entry.later <= revision) entry.later = undefined;
}

function noteRemoteRevision(id: string, revision: number, token: string) {
	const entry = entries.get(id);
	if (!entry || revision <= entry.revision) return;
	if (isLive(id)) {
		entry.later = Math.max(entry.later ?? 0, revision);
		return;
	}
	refetchChat(token, id);
}

function catchUp(id: string) {
	const entry = entries.get(id);
	if (!entry?.later || entry.later <= entry.revision || isLive(id)) return;
	entry.later = undefined;
	const token = typeof localStorage !== 'undefined' ? localStorage.token : '';
	if (!token) return;
	refetchChat(token, id);
}

export function dropChat(id: string) {
	entries.delete(id);
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
			const entry = putChat(document, entries.get(id)?.artifacts ?? null);
			return entry?.document ?? document;
		})
		.finally(() => {
			if (inflight.get(id) === job) inflight.delete(id);
		});
	inflight.set(id, job);
	return job;
}

export async function documentForOpen(token: string, id: string) {
	const pending = inflight.get(id);
	if (pending) await pending.catch(() => null);
	if (hasDocument(id)) {
		return { document: entries.get(id)?.document, fromMemory: true };
	}
	const document = await loadCachedChat(token, id, false);
	return { document, fromMemory: false };
}

const gapFetchedAt = new Map<string, number>();

function noteStreamGap(id: string, token: string) {
	if (inflight.has(id)) return;
	// Heartbeats and tokens keep arriving while a download is the wrong
	// fix. One look is enough; the next one waits until this window passes.
	const now = Date.now();
	if (now - (gapFetchedAt.get(id) ?? 0) < TURN_CHECK_MS) return;
	gapFetchedAt.set(id, now);
	refetchChat(token, id)
		.then((document) => {
			if (document && id === get(chatId)) notify(id, document);
		})
		.catch((error) => console.error(error));
}

/**
 * Write a socket event into a cached chat. Every chat, including the one
 * on screen, is updated here. The screen only paints the result.
 * A missing message is a gap: download that chat once.
 */
const TURN_ACTIVITY_TYPES = new Set([
	'status',
	'chat:completion',
	'chat:message:delta',
	'message',
	'chat:message',
	'replace',
	'chat:message:files',
	'files',
	'source',
	'citation'
]);

export function isTranscriptEvent(type: string | null) {
	return TURN_ACTIVITY_TYPES.has(type);
}

/** Activity and the revision token. The transcript write stays in one place below. */
function absorbTurnSignal(event: any) {
	const id = event?.chat_id;
	if (!id || id === 'local') return;
	const type = event?.data?.type ?? null;
	const data = event?.data?.data ?? null;
	if (TURN_ACTIVITY_TYPES.has(type)) noteTurnActivity(id);
	if (type !== 'chat:completion') return;
	const revision = Number(data?.revision);
	if (Number.isFinite(revision)) setRevision(id, revision);
}

export function applyCachedStreamEvent(event: any, token: string) {
	const id = event?.chat_id;
	if (!id || id === 'local') return;
	const type = event?.data?.type ?? null;
	absorbTurnSignal(event);
	let wrote = false;
	try {
		wrote = writeCachedStream(event, token);
	} finally {
		if (wrote && id === openId && TURN_ACTIVITY_TYPES.has(type)) {
			for (const listener of openTranscriptListeners) {
				try {
					listener(event);
				} catch (error) {
					console.error(error);
				}
			}
		}
	}
}

function writeCachedStream(event: any, token: string) {
	const id = event?.chat_id;
	const entry = entries.get(id);
	if (!entry?.document) return false;
	entry.touched = Date.now();
	const type = event?.data?.type ?? null;
	const data = event?.data?.data ?? null;
	if (type === 'chat:title') {
		const title = typeof data === 'string' ? data : data?.title;
		if (title) {
			entry.document.title = title;
			if (entry.document.chat) entry.document.chat.title = title;
		}
		return false;
	}
	const messageId = event?.message_id;
	if (!messageId) return false;
	const messages = entry.document?.chat?.history?.messages;
	if (!messages) {
		noteStreamGap(id, token);
		return false;
	}
	const message = messages[messageId];
	if (!message) {
		noteStreamGap(id, token);
		return false;
	}
	if (type === 'status') {
		if (message.done === true) return false;
		if (data?.action === 'generation_heartbeat') return false;
		if (message.statusHistory) message.statusHistory.push(data);
		else message.statusHistory = [data];
		return true;
	}
	if (type === 'chat:completion') {
		const lost = message.error?.content === GENERATION_LOST_MESSAGE;
		if (message.done === true && !data?.error && !lost) return false;
		if (lost && !data?.error) delete message.error;
		if (data?.error) message.error = data.error;
		if (data?.sources) message.sources = data.sources;
		if (data?.usage) message.usage = accumulateUsage(message.usage, data.usage);
		if (data?.selected_model_id) {
			message.selectedModelId = data.selected_model_id;
			message.arena = true;
		}
		if (data?.choices) {
			const choice = data.choices[0];
			const piece = choice?.message?.content ?? choice?.delta?.content ?? '';
			if (piece && !(message.content === '' && piece === '\n')) {
				message.content = `${message.content || ''}${piece}`;
			}
		}
		if (data?.content) message.content = data.content;
		if (data?.done) {
			message.done = true;
			if (isLive(id)) endLive(messageId);
		}
		markUnseenMessages(id);
		return true;
	}
	if (message.done === true) return false;
	if (type === 'chat:message:delta' || type === 'message') {
		message.content = `${message.content || ''}${data?.content || ''}`;
	} else if (type === 'chat:message' || type === 'replace') {
		message.content = data?.content ?? '';
	} else if (type === 'chat:message:files' || type === 'files') {
		message.files = data?.files;
	} else if (type === 'source' || type === 'citation') {
		if (data?.type === 'code_execution') {
			if (!message.code_executions) message.code_executions = [];
			const index = message.code_executions.findIndex((item) => item?.id === data?.id);
			if (index === -1) message.code_executions.push(data);
			else message.code_executions[index] = data;
		} else if (message.sources) {
			message.sources.push(data);
		} else {
			message.sources = [data];
		}
	} else {
		return false;
	}
	markUnseenMessages(id);
	entry.touched = Date.now();
	return true;
}

export function onChatUpdated(id: string, revision: number, token: string) {
	if (!id || !entries.has(id)) return;
	noteRemoteRevision(id, revision, token);
}

const artifactInflight = new Map<string, Promise<any[] | null>>();

async function fetchArtifactList(
	token: string,
	id: string,
	background: boolean
): Promise<any[] | null> {
	try {
		const res = await fetch(`${WEBUI_API_BASE_URL}/chats/${id}/artifacts`, {
			headers: { authorization: `Bearer ${token}` },
			...(background ? { priority: 'low' as const } : {})
		} as RequestInit);
		if (!res.ok) return null;
		const files = await res.json();
		return Array.isArray(files) ? files : null;
	} catch (error) {
		console.error(error);
		return null;
	}
}

/** Artifact list for a chat. Joins a fetch already in flight. */
export function ensureArtifacts(token: string, id: string, background = false) {
	const cached = artifactListFor(id);
	if (Array.isArray(cached)) return Promise.resolve(cached);
	return fetchArtifacts(token, id, background);
}

/** Replace the cached list. Used after this tab changes the files. */
export function refreshArtifacts(token: string, id: string) {
	const job = fetchArtifactList(token, id, false)
		.then((files) => {
			if (artifactInflight.get(id) !== job) return Array.isArray(files) ? files : null;
			if (Array.isArray(files)) rememberArtifacts(id, files);
			return Array.isArray(files) ? files : null;
		})
		.finally(() => {
			if (artifactInflight.get(id) === job) artifactInflight.delete(id);
		});
	artifactInflight.set(id, job);
	return job;
}

function fetchArtifacts(token: string, id: string, background: boolean) {
	const pending = artifactInflight.get(id);
	if (pending) return pending;
	const job = fetchArtifactList(token, id, background)
		.then((files) => {
			if (artifactInflight.get(id) !== job) return Array.isArray(files) ? files : null;
			if (Array.isArray(files)) rememberArtifacts(id, files);
			return Array.isArray(files) ? files : null;
		})
		.finally(() => {
			if (artifactInflight.get(id) === job) artifactInflight.delete(id);
		});
	artifactInflight.set(id, job);
	return job;
}

/**
 * One fill for every chat. The transcript and the artifact list are separate
 * requests. The promise resolves when the transcript is in the cache; a click
 * that arrives while this is running waits on the same promise.
 */
function loadCachedChat(token: string, id: string, background: boolean, minRevision = 0) {
	void ensureArtifacts(token, id, background);
	const pending = inflight.get(id);
	if (pending) return pending;
	const entry = entries.get(id);
	if (entry?.document && entry.revision >= minRevision) {
		return Promise.resolve(entry.document);
	}

	const job = getChatById(token, id, background ? 'low' : undefined)
		.then((document) => {
			if (!document?.id) return null;
			const stored = putChat(document, artifactListFor(document.id));
			if (document.id === openId && stored?.document) notify(document.id, stored.document);
			syncWatch();
			return stored?.document ?? document;
		})
		.finally(() => {
			if (inflight.get(id) === job) inflight.delete(id);
		});
	inflight.set(id, job);
	return job;
}

export async function preloadRecent(token: string, organizationId: string) {
	if (!organizationId) return;
	recentOrganizationId = organizationId;
	let refs: { id?: string; revision?: number }[] = [];
	try {
		const rows = await getRecentChats(token);
		if (Array.isArray(rows)) refs = rows;
	} catch (error) {
		console.error(error);
		return;
	}
	const queue: { id: string; minRevision: number }[] = [];
	for (const ref of refs) {
		const id = ref?.id;
		if (!id) continue;
		const incoming = Number(ref.revision ?? 0);
		const minRevision = Number.isFinite(incoming) ? incoming : 0;
		const existing = entries.get(id);
		if (existing?.document && existing.revision >= minRevision && Array.isArray(existing.artifacts)) {
			continue;
		}
		queue.push({ id, minRevision });
	}
	syncWatch();
	await Promise.all(
		queue.map(async (job) => {
			try {
				await loadCachedChat(token, job.id, true, job.minRevision);
			} catch (error) {
				console.error(error);
			}
		})
	);
	syncWatch();
}

/** Re-pull the recent window after the socket drops and reconnects. */
export async function refreshRecent(token: string) {
	if (!token || !recentOrganizationId) return;
	await preloadRecent(token, recentOrganizationId);
}

export function cachedArtifacts(id: string) {
	return entries.get(id)?.artifacts ?? null;
}
