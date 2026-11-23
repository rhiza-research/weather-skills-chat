import { get } from 'svelte/store';
import { expect, test, vi } from 'vitest';
import { chatArtifactLists } from '$lib/stores';
import { putChat, refreshCachedArtifacts, setOpenChat } from './cache';

const chat = (id: string) => ({ id, meta: { revision: 1 }, chat: { history: { messages: {} } } });
const file = (name: string) => ({ path: name, name, kind: 'file' });

test('a reconnect re-lists the open chat; the others re-list when opened, painting the old list first', async () => {
	vi.stubGlobal('localStorage', { token: 'token' });
	const listed: string[] = [];
	vi.stubGlobal(
		'fetch',
		vi.fn(async (url: string) => {
			const id = url.split('/').at(-2) as string;
			listed.push(id);
			return { ok: true, json: async () => [file(`new-${id}`)] };
		})
	);
	putChat(chat('open'), [file('old-open')]);
	putChat(chat('other'), [file('old-other')]);
	setOpenChat('open');

	await refreshCachedArtifacts('token');
	expect(listed).toEqual(['open']);
	expect(get(chatArtifactLists).open).toEqual([file('new-open')]);

	setOpenChat('other');
	expect(get(chatArtifactLists).other).toEqual([file('old-other')]);
	await vi.waitFor(() => expect(get(chatArtifactLists).other).toEqual([file('new-other')]));
	expect(listed).toEqual(['open', 'other']);

	// Fresh now: opening it again does not list it again.
	setOpenChat('open');
	setOpenChat('other');
	expect(listed).toEqual(['open', 'other']);
	vi.unstubAllGlobals();
});
