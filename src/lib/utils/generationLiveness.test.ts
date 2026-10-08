import { expect, test } from 'vitest';
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
	expect(formatGenerationRequestError({ status: 409, detail: 'Another user has edited the chat. Please try again.' })).toBe(
		'Another user has edited the chat. Please try again.'
	);
	expect(formatGenerationRequestError('409 Chat was updated')).toBe(
		'Another user has edited the chat. Please try again.'
	);
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
