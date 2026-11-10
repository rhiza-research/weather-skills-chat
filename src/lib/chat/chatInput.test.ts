import { expect, test } from 'vitest';
import { chatInputWorthSaving, emptyChatInput, parseChatInput } from './chatInput';

test('switches are kept without a draft', () => {
	expect(chatInputWorthSaving({ ...emptyChatInput(), readArtifactsEnabled: true })).toBe(true);
	expect(chatInputWorthSaving({ ...emptyChatInput(), webSearchEnabled: true })).toBe(true);
	expect(chatInputWorthSaving({ ...emptyChatInput(), builtinFeatures: { email: false } })).toBe(
		true
	);
});

test('an empty chat bar is not kept', () => {
	expect(chatInputWorthSaving(emptyChatInput())).toBe(false);
});

test('a saved chat bar fills in what it lacks', () => {
	const input = parseChatInput(JSON.stringify({ prompt: 'hi', readArtifactsEnabled: true }));
	expect(input).toEqual({ ...emptyChatInput(), prompt: 'hi', readArtifactsEnabled: true });
	expect(parseChatInput('not json')).toEqual(emptyChatInput());
	expect(parseChatInput(null)).toEqual(emptyChatInput());
});
