import { expect, test } from 'vitest';
import {
	applyCachedStreamEvent,
	beginLive,
	endLive,
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
	putChat(document, null, true);
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
	putChat(open, null, true);
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
	putChat(local, null, true);
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
		null,
		true
	);
	expect(local.chat.history).toBe(history);
	expect(history.messages.asst.content).toBe('hi');
	expect(history.messages.other.content).toBe('x');
	endLive('asst');
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
	putChat(live, null, true);
	beginLive('chat-switch', 'asst');
	await settleLoadedTurn('chat-switch', 'token', false);
	expect(live.chat.history.messages.asst.done).toBe(false);
	expect(live.chat.history.messages.asst.error).toBeUndefined();
	endLive('asst');
});
