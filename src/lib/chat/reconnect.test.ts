import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { expect, test } from 'vitest';
import { afterSocketReconnect } from './reconnect';

const socketSource = readFileSync(
	resolve(dirname(fileURLToPath(import.meta.url)), '../utils/socket.ts'),
	'utf8'
);

test('reconnect refreshes the sidebar and recent cache, not only cached transcripts', async () => {
	const calls: string[] = [];
	await afterSocketReconnect({
		refreshRecent: async () => {
			calls.push('recent');
		},
		refreshSidebar: async () => {
			calls.push('sidebar');
		},
		refreshArtifacts: async () => {
			calls.push('artifacts');
		}
	});
	expect(calls).toContain('recent');
	expect(calls).toContain('sidebar');
	expect(calls).toContain('artifacts');
});

test('the live socket reconnect path calls afterSocketReconnect', () => {
	expect(socketSource).toMatch(/afterSocketReconnect/);
});
