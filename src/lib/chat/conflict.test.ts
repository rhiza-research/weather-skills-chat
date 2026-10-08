import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { expect, test } from 'vitest';

const chatSource = readFileSync(
	resolve(dirname(fileURLToPath(import.meta.url)), '../components/chat/Chat.svelte'),
	'utf8'
);
import {
	CHAT_BUSY_MESSAGE,
	CHAT_CONFLICT_MESSAGE,
	conflictRevision,
	isChatConflict,
	recoverEditConflict,
	recoverSendConflict
} from './conflict';

test('conflict copy talks about another user, not a raw 409', () => {
	expect(CHAT_CONFLICT_MESSAGE).toMatch(/another user has edited the chat/i);
	expect(CHAT_CONFLICT_MESSAGE).not.toMatch(/409/);
	expect(CHAT_BUSY_MESSAGE).toMatch(/another window/i);
});

test('isChatConflict reads status and revision from a parsed error', () => {
	expect(isChatConflict({ status: 409, revision: 7, detail: CHAT_CONFLICT_MESSAGE })).toBe(true);
	expect(isChatConflict({ status: 400, detail: 'nope' })).toBe(false);
	expect(conflictRevision({ status: 409, revision: 7 })).toBe(7);
});

test('a send conflict refetches and retries once', async () => {
	const calls: string[] = [];
	const result = await recoverSendConflict({
		refetch: async () => {
			calls.push('refetch');
		},
		retry: async () => {
			calls.push('retry');
		}
	});
	expect(result).toBe('retried');
	expect(calls).toEqual(['refetch', 'retry']);
});

test('an edit conflict refetches then writes the local edit again', async () => {
	const calls: string[] = [];
	const result = await recoverEditConflict({
		refetch: async () => {
			calls.push('refetch');
		},
		reapply: async () => {
			calls.push('reapply');
		}
	});
	expect(result).toBe('reapplied');
	expect(calls).toEqual(['refetch', 'reapply']);
});

test('send and edit handlers recover from a 409 instead of ending the live turn or dropping the edit', () => {
	expect(chatSource).toMatch(/recoverSendConflict/);
	expect(chatSource).toMatch(/recoverEditConflict/);
});
