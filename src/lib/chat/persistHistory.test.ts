import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { expect, test } from 'vitest';
import { shouldPersistHistory } from './persistHistory';

const messagesSource = readFileSync(
	resolve(dirname(fileURLToPath(import.meta.url)), '../components/chat/Messages.svelte'),
	'utf8'
);

test('a temporary chat does not persist history to the server', () => {
	expect(shouldPersistHistory(true, 'chat-1')).toBe(false);
	expect(shouldPersistHistory(true, 'local')).toBe(false);
});

test('a saved chat persists history', () => {
	expect(shouldPersistHistory(false, 'chat-1')).toBe(true);
});

test('a local id is never persisted', () => {
	expect(shouldPersistHistory(false, 'local')).toBe(false);
	expect(shouldPersistHistory(false, '')).toBe(false);
	expect(shouldPersistHistory(false, null)).toBe(false);
});

test('message delete uses the same persist guard as edit', () => {
	expect(messagesSource).toMatch(/shouldPersistHistory/);
	const deleteIndex = messagesSource.indexOf('const deleteMessage');
	const deleteBlock = messagesSource.slice(deleteIndex, deleteIndex + 800);
	expect(deleteBlock).toMatch(/shouldPersistHistory/);
});
