import { expect, test } from 'vitest';
import { CHAT_CONFLICT_MESSAGE, parseApiError } from './response';

function jsonResponse(status: number, body: unknown) {
	return new Response(JSON.stringify(body), {
		status,
		headers: { 'content-type': 'application/json' }
	});
}

test('parseApiError keeps the 409 revision and a readable message', async () => {
	const error = await parseApiError(
		jsonResponse(409, { detail: { message: 'Chat was updated', revision: 7 } })
	);
	expect(error.status).toBe(409);
	expect(error.revision).toBe(7);
	expect(error.detail).toBe(CHAT_CONFLICT_MESSAGE);
	expect(error.detail).not.toMatch(/409/);
});

test('parseApiError keeps a lock-timeout message', async () => {
	const error = await parseApiError(
		jsonResponse(409, {
			detail: {
				message: 'This chat is being edited in another window. Please try again shortly.'
			}
		})
	);
	expect(error.detail).toMatch(/another window/i);
});
