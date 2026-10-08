import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { expect, test } from 'vitest';
import { applyChatListRow } from './listRow';

const layoutSource = readFileSync(
	resolve(dirname(fileURLToPath(import.meta.url)), '../../routes/+layout.svelte'),
	'utf8'
);

const orgA = 'org-a';
const orgB = 'org-b';

const row = (id: string, extra: Record<string, unknown> = {}) => ({
	id,
	organization_id: orgA,
	updated_at: 100,
	title: id,
	...extra
});

test('a chat:list row from another organization is ignored', () => {
	const existing = [row('keep')];
	const next = applyChatListRow(row('foreign', { organization_id: orgB, updated_at: 200 }), existing, [], {
		organizationId: orgA
	});
	expect(next.chats.map((item) => item.id)).toEqual(['keep']);
});

test('a filed chat is not added to the unfiled list', () => {
	const existing = [row('keep')];
	const next = applyChatListRow(row('filed', { folder_id: 'folder-1', updated_at: 200 }), existing, [], {
		organizationId: orgA,
		folderId: null
	});
	expect(next.chats.map((item) => item.id)).toEqual(['keep']);
});

test('a chat that moves into a folder is removed from the unfiled list', () => {
	const existing = [row('filed'), row('keep')];
	const next = applyChatListRow(
		row('filed', { folder_id: 'folder-1', updated_at: 200 }),
		existing,
		[],
		{ organizationId: orgA, folderId: null }
	);
	expect(next.chats.map((item) => item.id)).toEqual(['keep']);
});

test('rows stay ordered by updated_at instead of always jumping to the top', () => {
	const existing = [row('newer', { updated_at: 300 }), row('older', { updated_at: 100 })];
	const next = applyChatListRow(row('older', { updated_at: 150 }), existing, [], {
		organizationId: orgA
	});
	expect(next.chats.map((item) => item.id)).toEqual(['newer', 'older']);
});

test('the app sidebar applies chat:list rows through applyChatListRow', () => {
	expect(layoutSource).toMatch(/applyChatListRow/);
	expect(layoutSource).toMatch(/from ['\"]\$lib\/chat\/listRow['\"]/);
});

test('a removed row leaves both the chat list and the pinned list', () => {
	const next = applyChatListRow(
		{ id: 'gone', removed: true },
		[row('gone'), row('keep')],
		[row('gone', { pinned: true })],
		{ organizationId: orgA }
	);
	expect(next.chats.map((item) => item.id)).toEqual(['keep']);
	expect(next.pinnedChats).toEqual([]);
});
