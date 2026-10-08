import { expect, test } from 'vitest';
import { parseApiError } from './response';

const jsonResponse = (status: number, body: unknown) =>
	new Response(JSON.stringify(body), {
		status,
		headers: { 'content-type': 'application/json' }
	});

test('a 409 keeps the server revision so the tab can adopt it', async () => {
	const error = await parseApiError(
		jsonResponse(409, {
			detail: { message: 'Another user has edited the chat. Please try again.', revision: 11 }
		})
	);
	expect(error.status).toBe(409);
	expect(error.revision).toBe(11);
	expect(String(error.detail)).toMatch(/another user has edited the chat/i);
});

test('a busy-chat write error stays user-readable', async () => {
	const error = await parseApiError(
		jsonResponse(409, {
			detail: {
				message: 'This chat is being edited by another window. Please try again shortly.'
			}
		})
	);
	expect(String(error.detail)).toMatch(/another window/i);
	expect(String(error.detail)).not.toMatch(/^409$/);
});
