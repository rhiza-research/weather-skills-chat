import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { expect, test } from 'vitest';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../../..');

const read = (relative: string) => readFileSync(resolve(root, relative), 'utf8');

test('nothing increments the unused artifactsRefresh store', () => {
	const files = [
		'src/routes/+layout.svelte',
		'src/lib/components/chat/Chat.svelte',
		'src/lib/components/chat/MessageInput.svelte'
	];
	for (const file of files) {
		expect(read(file), file).not.toMatch(/artifactsRefresh\.update/);
	}
});

test('putChat call sites do not pass an ignored third argument', () => {
	const files = [
		'src/lib/components/chat/Chat.svelte',
		'src/lib/components/chat/Messages.svelte',
		'src/lib/chat/cache.turn.test.ts'
	];
	for (const file of files) {
		expect(read(file), file).not.toMatch(/putChat\([^)]+,\s*[^)]+,\s*true\s*\)/);
	}
});
