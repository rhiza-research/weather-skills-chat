import { afterEach, expect, test, vi } from 'vitest';
import { stopTask } from './index';

const originalFetch = globalThis.fetch;

afterEach(() => {
	globalThis.fetch = originalFetch;
	vi.unstubAllGlobals();
});

const respond = (status: number, body: unknown) => {
	globalThis.fetch = vi.fn(
		async () =>
			new Response(JSON.stringify(body), {
				status,
				headers: { 'content-type': 'application/json' }
			})
	) as typeof fetch;
};

test('stopping a task the backend no longer has is not an error', async () => {
	respond(404, { detail: 'Task with ID abc not found.' });
	await expect(stopTask('token', 'abc')).resolves.toBeNull();
});

test('other stop failures still reach the caller', async () => {
	respond(500, { detail: 'boom' });
	await expect(stopTask('token', 'abc')).rejects.toBe('boom');
});
