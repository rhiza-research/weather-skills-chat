import { beforeEach, expect, test } from 'vitest';
import { MAX_QUEUED_SENDS, readQueuedSends, writeQueuedSends } from './queuedSend';

beforeEach(() => {
	const store = new Map<string, string>();
	globalThis.localStorage = {
		getItem: (k: string) => store.get(k) ?? null,
		setItem: (k: string, v: string) => void store.set(k, String(v)),
		removeItem: (k: string) => void store.delete(k),
		clear: () => store.clear(),
		key: (i: number) => [...store.keys()][i] ?? null,
		get length() {
			return store.size;
		}
	} as Storage;
});

test('queued sends are read back in order for their own chat only', () => {
	writeQueuedSends('chat-a', ['plot the rainfall', 'now the temperature']);
	expect(readQueuedSends('chat-a')).toEqual(['plot the rainfall', 'now the temperature']);
	expect(readQueuedSends('chat-b')).toEqual([]);
});

test('an empty queue clears the stored entry', () => {
	writeQueuedSends('chat-a', ['plot the rainfall']);
	writeQueuedSends('chat-a', []);
	expect(readQueuedSends('chat-a')).toEqual([]);
	expect(localStorage.length).toBe(0);
});

test('new and temporary chats are not stored', () => {
	writeQueuedSends('', ['hello']);
	writeQueuedSends('local', ['hello']);
	expect(localStorage.length).toBe(0);
	expect(readQueuedSends('local')).toEqual([]);
});

test('a corrupt or oversized entry reads back within the limit', () => {
	localStorage.setItem('chat-queued-send-chat-a', '{not json');
	expect(readQueuedSends('chat-a')).toEqual([]);

	localStorage.setItem(
		'chat-queued-send-chat-a',
		JSON.stringify({ prompts: ['a', 7, 'b', 'c', 'd', 'e'] })
	);
	expect(MAX_QUEUED_SENDS).toBe(3);
	expect(readQueuedSends('chat-a')).toEqual(['a', 'b', 'c']);
});
