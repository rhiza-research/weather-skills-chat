import { afterEach, expect, test, vi } from 'vitest';
import { get } from 'svelte/store';
import { chatArtifactLists } from '$lib/stores';
import { ensureArtifacts, rememberArtifacts } from './cache';

const partial = [
	{ path: 'notes.csv', provenance: ['plot'] },
	{ path: 'runs', is_dir: true, truncated: true }
];
const full = [
	{ path: 'notes.csv', provenance: ['plot'] },
	{ path: 'runs', is_dir: true },
	{ path: 'runs/out.csv' }
];

function stubFetch(byQuery: Record<string, any[]>) {
	const urls: string[] = [];
	const resolvers: Array<() => void> = [];
	vi.stubGlobal(
		'fetch',
		vi.fn((url: string) => {
			urls.push(url);
			const body = url.includes('?depth=1') ? byQuery.partial : byQuery.full;
			return new Promise((resolve) =>
				resolvers.push(() => resolve({ ok: true, json: async () => body }))
			);
		})
	);
	const flush = async () => {
		while (resolvers.length) resolvers.shift()!();
		await new Promise((r) => setTimeout(r, 0));
	};
	return { urls, flush };
}

afterEach(() => {
	vi.unstubAllGlobals();
	chatArtifactLists.set({});
});

test('the background prefetch lists only the top level, with provenance', async () => {
	const { urls, flush } = stubFetch({ partial, full });
	const job = ensureArtifacts('t', 'chat-pre', true);
	await flush();
	expect(await job).toEqual(partial);
	expect(urls).toEqual([expect.stringMatching(/\/chats\/chat-pre\/artifacts\?depth=1$/)]);
	expect(urls[0]).not.toContain('provenance');
});

test('opening a chat with a prefetched top level fetches the whole tree', async () => {
	rememberArtifacts('chat-open', partial);
	const { urls, flush } = stubFetch({ partial, full });
	const job = ensureArtifacts('t', 'chat-open');
	await flush();
	expect(await job).toEqual(full);
	expect(urls).toEqual([expect.stringMatching(/\/chats\/chat-open\/artifacts$/)]);
	expect(get(chatArtifactLists)['chat-open']).toEqual(full);
});

test('a complete cached list is kept when the chat opens', async () => {
	rememberArtifacts('chat-done', full);
	const { urls } = stubFetch({ partial, full });
	expect(await ensureArtifacts('t', 'chat-done')).toEqual(full);
	expect(urls).toEqual([]);
});

test('opening a chat while its prefetch runs fetches the whole tree, and it wins', async () => {
	const { urls, flush } = stubFetch({ partial, full });
	const prefetch = ensureArtifacts('t', 'chat-race', true);
	const open = ensureArtifacts('t', 'chat-race');
	await flush();
	await prefetch;
	expect(await open).toEqual(full);
	expect(urls).toHaveLength(2);
	expect(get(chatArtifactLists)['chat-race']).toEqual(full);
});

test('a prefetch that lands after the whole tree arrived does not replace it', async () => {
	const { flush } = stubFetch({ partial, full });
	const prefetch = ensureArtifacts('t', 'chat-socket', true);
	rememberArtifacts('chat-socket', full); // chat:artifacts from the server
	await flush();
	await prefetch;
	expect(get(chatArtifactLists)['chat-socket']).toEqual(full);
});
