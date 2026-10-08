import { afterEach, expect, test, vi } from 'vitest';
import { generateOpenAIChatCompletion } from './openai';
import { CHAT_CONFLICT_MESSAGE, isChatConflict } from '../chat/conflict';

const originalFetch = globalThis.fetch;

afterEach(() => {
	globalThis.fetch = originalFetch;
	vi.unstubAllGlobals();
});

test('a 409 completion keeps status and revision so send can recover', async () => {
	globalThis.fetch = vi.fn(async () =>
		new Response(
			JSON.stringify({
				detail: { message: CHAT_CONFLICT_MESSAGE, revision: 11 }
			}),
			{ status: 409, headers: { 'content-type': 'application/json' } }
		)
	) as typeof fetch;

	const error = await generateOpenAIChatCompletion('token', { model: 'x' }).then(
		() => null,
		(thrown) => thrown
	);
	expect(error).toBeTruthy();
	expect(typeof error).toBe('object');
	expect(error.status).toBe(409);
	expect(error.revision).toBe(11);
	expect(isChatConflict(error)).toBe(true);
	expect(String(error.detail)).toMatch(/another user has edited the chat/i);
});
