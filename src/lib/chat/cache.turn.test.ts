import { expect, test } from 'vitest';
import {
	applyCachedStreamEvent,
	beginLive,
	endLive,
	endOfBranch,
	holdPendingTurn,
	isPendingMessage,
	mergeFiles,
	moveTurnToEnd,
	putChat,
	revisionOf,
	setOpenChat,
	settleLoadedTurn
} from './cache';

const document = {
	id: 'chat-a',
	meta: { revision: 2 },
	chat: {
		history: {
			currentId: 'asst-1',
			messages: {
				'asst-1': { id: 'asst-1', role: 'assistant', content: '', done: false }
			}
		}
	}
};

test('a background chat adopts the completion revision and marks the turn done', () => {
	putChat(document, null);
	setOpenChat('chat-b');
	applyCachedStreamEvent(
		{
			chat_id: 'chat-a',
			message_id: 'asst-1',
			data: {
				type: 'chat:completion',
				data: { done: true, content: 'done', revision: 4 }
			}
		},
		'token'
	);
	expect(revisionOf('chat-a')).toBe(4);
	expect(document.chat.history.messages['asst-1'].done).toBe(true);
	expect(document.chat.history.messages['asst-1'].content).toBe('done');
});

test('the open chat is written by the same path as a background chat', () => {
	const open = {
		id: 'chat-open',
		meta: { revision: 1 },
		chat: {
			history: {
				currentId: 'asst-2',
				messages: {
					'asst-2': { id: 'asst-2', role: 'assistant', content: 'partial', done: false }
				}
			}
		}
	};
	putChat(open, null);
	setOpenChat('chat-open');
	applyCachedStreamEvent(
		{
			chat_id: 'chat-open',
			message_id: 'asst-2',
			data: {
				type: 'chat:completion',
				data: { done: true, content: 'final', revision: 3 }
			}
		},
		'token'
	);
	expect(revisionOf('chat-open')).toBe(3);
	expect(open.chat.history.messages['asst-2'].done).toBe(true);
	expect(open.chat.history.messages['asst-2'].content).toBe('final');
});

test('a download during a live turn keeps the history object already on screen', () => {
	const local = {
		id: 'chat-live',
		meta: { revision: 1 },
		chat: {
			history: {
				currentId: 'asst',
				messages: {
					asst: { id: 'asst', role: 'assistant', content: 'hi', done: false }
				}
			}
		}
	};
	putChat(local, null);
	beginLive('chat-live', 'asst');
	const history = local.chat.history;
	putChat(
		{
			id: 'chat-live',
			meta: { revision: 2 },
			chat: {
				history: {
					currentId: 'asst',
					messages: {
						asst: { id: 'asst', role: 'assistant', content: '', done: false },
						other: { id: 'other', role: 'assistant', content: 'x', done: true }
					}
				}
			}
		},
		null
	);
	expect(local.chat.history).toBe(history);
	expect(history.messages.asst.content).toBe('hi');
	expect(history.messages.other.content).toBe('x');
	endLive('asst');
});

test('putChat drops messages the newer copy no longer has', () => {
	const local = {
		id: 'chat-delete',
		meta: { revision: 1 },
		chat: {
			history: {
				currentId: 'keep',
				messages: {
					keep: { id: 'keep', role: 'assistant', content: 'stay', done: true },
					gone: { id: 'gone', role: 'user', content: 'delete me', done: true }
				}
			}
		}
	};
	putChat(local);
	putChat({
		id: 'chat-delete',
		meta: { revision: 2 },
		chat: {
			history: {
				currentId: 'keep',
				messages: {
					keep: { id: 'keep', role: 'assistant', content: 'stay', done: true }
				}
			}
		}
	});
	expect(local.chat.history.messages.gone).toBeUndefined();
	expect(local.chat.history.messages.keep.content).toBe('stay');
});

test('putChat ignores an older revision so a late fetch cannot rewind the tree', () => {
	const local = {
		id: 'chat-stale',
		meta: { revision: 5 },
		chat: {
			history: {
				currentId: 'asst',
				messages: {
					asst: { id: 'asst', role: 'assistant', content: 'newer', done: true }
				}
			}
		}
	};
	putChat(local);
	putChat({
		id: 'chat-stale',
		meta: { revision: 2 },
		chat: {
			history: {
				currentId: 'asst',
				messages: {
					asst: { id: 'asst', role: 'assistant', content: 'older', done: true }
				}
			}
		}
	});
	expect(local.chat.history.messages.asst.content).toBe('newer');
	expect(revisionOf('chat-stale')).toBe(5);
});

test('opening a chat this tab is already generating does not mark it lost', async () => {
	const live = {
		id: 'chat-switch',
		meta: { revision: 1 },
		chat: {
			history: {
				currentId: 'asst',
				messages: {
					asst: { id: 'asst', role: 'assistant', content: 'hi', done: false }
				}
			}
		}
	};
	putChat(live, null);
	beginLive('chat-switch', 'asst');
	await settleLoadedTurn('chat-switch', 'token', false);
	expect(live.chat.history.messages.asst.done).toBe(false);
	expect(live.chat.history.messages.asst.error).toBeUndefined();
	endLive('asst');
});

const turnChat = (id: string, revision: number, messages: Record<string, any>, currentId: string) => ({
	id,
	meta: { revision },
	chat: { history: { currentId, messages } }
});

const stored = () => ({
	'u-1': { id: 'u-1', parentId: null, childrenIds: ['a-1'], role: 'user', content: 'hi', done: true },
	'a-1': { id: 'a-1', parentId: 'u-1', childrenIds: [], role: 'assistant', content: 'yo', done: true }
});

/** This tab sends u-2 / a-2 after a-1, the way submitPrompt builds them. */
const sendLocally = (document: any) => {
	const messages = document.chat.history.messages;
	messages['a-1'].childrenIds.push('u-2');
	messages['u-2'] = { id: 'u-2', parentId: 'a-1', childrenIds: ['a-2'], role: 'user', content: 'mine' };
	messages['a-2'] = { id: 'a-2', parentId: 'u-2', childrenIds: [], role: 'assistant', content: '' };
	document.chat.history.currentId = 'a-2';
};

/** Another tab already stored u-3 / a-3 after a-1. */
const otherTabTurn = () => {
	const messages: Record<string, any> = stored();
	messages['a-1'].childrenIds = ['u-3'];
	messages['u-3'] = { id: 'u-3', parentId: 'a-1', childrenIds: ['a-3'], role: 'user', content: 'theirs' };
	messages['a-3'] = { id: 'a-3', parentId: 'u-3', childrenIds: [], role: 'assistant', content: 'ok', done: true };
	return messages;
};

test('a reload during a conflicted send keeps the unsent prompt and its reply', () => {
	const document = turnChat('chat-pending', 1, stored(), 'a-1');
	putChat(document, null);
	setOpenChat('chat-pending');
	sendLocally(document);
	holdPendingTurn('chat-pending', ['u-2', 'a-2']);

	putChat(turnChat('chat-pending', 2, otherTabTurn(), 'a-3'), null);

	const messages = document.chat.history.messages;
	expect(messages['u-2']?.content).toBe('mine');
	expect(messages['a-2']).toBeTruthy();
	expect(messages['a-1'].childrenIds).toContain('u-2');
	expect(messages['u-3']?.content).toBe('theirs');
});

test('a retried send moves the prompt after the newest message instead of branching', () => {
	const document = turnChat('chat-append', 1, stored(), 'a-1');
	putChat(document, null);
	setOpenChat('chat-append');
	sendLocally(document);
	holdPendingTurn('chat-append', ['u-2', 'a-2']);
	putChat(turnChat('chat-append', 2, otherTabTurn(), 'a-3'), null);

	expect(moveTurnToEnd('chat-append', 'u-2')).toBe('a-3');

	const messages = document.chat.history.messages;
	expect(messages['u-2'].parentId).toBe('a-3');
	expect(messages['a-3'].childrenIds).toEqual(['u-2']);
	expect(messages['a-1'].childrenIds).toEqual(['u-3']);
	expect(document.chat.history.currentId).toBe('a-2');
});

test('once the server stores the turn, a later reload follows the server', () => {
	const document = turnChat('chat-confirm', 1, stored(), 'a-1');
	putChat(document, null);
	setOpenChat('chat-confirm');
	sendLocally(document);
	holdPendingTurn('chat-confirm', ['u-2', 'a-2']);

	const confirmed: Record<string, any> = stored();
	confirmed['a-1'].childrenIds = ['u-2'];
	confirmed['u-2'] = { id: 'u-2', parentId: 'a-1', childrenIds: ['a-2'], role: 'user', content: 'mine' };
	confirmed['a-2'] = { id: 'a-2', parentId: 'u-2', childrenIds: [], role: 'assistant', content: 'done', done: true };
	putChat(turnChat('chat-confirm', 2, confirmed, 'a-2'), null);
	expect(isPendingMessage('chat-confirm', 'u-2')).toBe(false);

	// Deleted elsewhere: the next reload removes it like any other message.
	putChat(turnChat('chat-confirm', 3, stored(), 'a-1'), null);
	expect(document.chat.history.messages['u-2']).toBeUndefined();
});

test('a regenerated reply keeps its stored prompt where it is', () => {
	const messages: Record<string, any> = stored();
	const document = turnChat('chat-regen', 1, messages, 'a-1');
	putChat(document, null);
	setOpenChat('chat-regen');
	messages['u-1'].childrenIds.push('a-1b');
	messages['a-1b'] = { id: 'a-1b', parentId: 'u-1', childrenIds: [], role: 'assistant', content: '' };
	holdPendingTurn('chat-regen', ['u-1', 'a-1b']);
	putChat(turnChat('chat-regen', 2, stored(), 'a-1'), null);

	expect(moveTurnToEnd('chat-regen', 'u-1')).toBe(null);
	expect(document.chat.history.messages['u-1'].parentId).toBe(null);
});

test('the newest message on a branch follows the last child and skips this tab\'s unsent ones', () => {
	const messages = otherTabTurn();
	messages['a-1'].childrenIds.push('u-x');
	messages['u-x'] = { id: 'u-x', parentId: 'a-1', childrenIds: [] };
	expect(endOfBranch(messages, 'a-1', new Set(['u-x']))).toBe('a-3');
	expect(endOfBranch(messages, 'a-3')).toBe('a-3');
	expect(endOfBranch(messages, null)).toBe(null);
});

test('the live copy keeps only the latest status and appends files without repeats', () => {
	const document = turnChat('chat-parts', 1, stored(), 'a-1');
	putChat(document, null);
	const send = (type: string, data: any) =>
		applyCachedStreamEvent({ chat_id: 'chat-parts', message_id: 'a-1', data: { type, data } }, 'token');
	const message = document.chat.history.messages['a-1'] as any;
	message.done = false;
	send('status', { description: 'Searching', done: false });
	send('status', { description: 'Searched 2 sites', done: true });
	expect(message.statusHistory).toEqual([{ description: 'Searched 2 sites', done: true }]);
	send('files', { files: [{ url: '/a.png' }] });
	send('files', { files: [{ url: '/a.png' }, { url: '/b.png' }] });
	expect(message.files).toEqual([{ url: '/a.png' }, { url: '/b.png' }]);
	expect(mergeFiles(undefined, [{ id: 'f' }, { id: 'f' }])).toEqual([{ id: 'f' }]);
});
