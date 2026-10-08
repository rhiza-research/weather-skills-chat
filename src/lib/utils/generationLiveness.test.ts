import { expect, test } from 'vitest';
import { CHAT_CONFLICT_MESSAGE } from '../chat/conflict';
import {
	SERVER_UNREACHABLE_MESSAGE,
	clearSpinningToolCalls,
	formatGenerationRequestError,
	isServerUnreachableError
} from './generationLiveness';

test('isServerUnreachableError detects common fetch failures', () => {
	expect(isServerUnreachableError('TypeError: Failed to fetch')).toBe(true);
	expect(isServerUnreachableError(new TypeError('Failed to fetch'))).toBe(true);
	expect(isServerUnreachableError(new TypeError('Load failed'))).toBe(true);
	expect(isServerUnreachableError('NetworkError when attempting to fetch resource.')).toBe(true);
	expect(isServerUnreachableError('validation failed')).toBe(false);
});

test('formatGenerationRequestError maps unreachable errors', () => {
	expect(formatGenerationRequestError(new TypeError('Failed to fetch'))).toBe(
		SERVER_UNREACHABLE_MESSAGE
	);
	expect(formatGenerationRequestError({ detail: 'model not found' })).toBe('model not found');
});

test('a 409 is shown as another user editing the chat, not as the status code', () => {
	expect(
		formatGenerationRequestError({
			status: 409,
			detail: CHAT_CONFLICT_MESSAGE,
			revision: 11
		})
	).toBe(CHAT_CONFLICT_MESSAGE);
	expect(
		formatGenerationRequestError({
			status: 409,
			detail: CHAT_CONFLICT_MESSAGE,
			revision: 11
		})
	).not.toMatch(/409/);
});

test('clearSpinningToolCalls marks incomplete tool details done', () => {
	const input =
		'<details type="tool_calls" done="false" name="plot"><summary>Executing...</summary></details>';
	const out = clearSpinningToolCalls(input);
	expect(out).toContain('done="true"');
	expect(out).not.toContain('done="false"');
});

test('clearSpinningToolCalls marks incomplete reasoning details done', () => {
	const input =
		'<details type="reasoning" done="false"><summary>Thinking…</summary>\npartial</details>';
	const out = clearSpinningToolCalls(input);
	expect(out).toContain('type="reasoning" done="true"');
	expect(out).not.toContain('done="false"');
});
