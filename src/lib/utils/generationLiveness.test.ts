import { expect, test } from 'vitest';
import {
	GENERATION_LOST_MESSAGE,
	SERVER_UNREACHABLE_MESSAGE,
	clearSpinningToolCalls,
	finalizeOrphanAssistantMessages,
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

test('clearSpinningToolCalls marks incomplete tool details done', () => {
	const input =
		'<details type="tool_calls" done="false" name="plot"><summary>Executing...</summary></details>';
	const out = clearSpinningToolCalls(input);
	expect(out).toContain('done="true"');
	expect(out).not.toContain('done="false"');
});

test('finalizeOrphanAssistantMessages fails incomplete assistants when no live task', () => {
	const messages = {
		a: {
			id: 'a',
			role: 'assistant',
			done: false,
			content:
				'<details type="tool_calls" done="false" name="x"><summary>Executing...</summary></details>'
		},
		b: { id: 'b', role: 'user', content: 'hi' },
		c: { id: 'c', role: 'assistant', done: true, content: 'ok' }
	};
	const count = finalizeOrphanAssistantMessages(messages, false);
	expect(count).toBe(1);
	expect(messages.a.done).toBe(true);
	expect(messages.a.error.content).toBe(GENERATION_LOST_MESSAGE);
	expect(messages.a.content).toContain('done="true"');
	expect(messages.c.done).toBe(true);
});

test('finalizeOrphanAssistantMessages leaves incomplete assistants when task is live', () => {
	const messages = {
		a: { id: 'a', role: 'assistant', done: false, content: '' }
	};
	const count = finalizeOrphanAssistantMessages(messages, true);
	expect(count).toBe(0);
	expect(messages.a.done).toBe(false);
	expect(messages.a.error).toBeUndefined();
});
