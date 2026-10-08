import { expect, test } from 'vitest';
import { shouldPlayCompletionSound } from './notifyCompletion';

test('a reply in another chat plays a chime while this tab is focused', () => {
	expect(
		shouldPlayCompletionSound({
			soundEnabled: true,
			isLastActiveTab: true,
			hasBeenActive: true,
			focusedOnThisChat: false
		})
	).toBe(true);
});

test('a reply in the open chat does not play a chime', () => {
	expect(
		shouldPlayCompletionSound({
			soundEnabled: true,
			isLastActiveTab: true,
			hasBeenActive: true,
			focusedOnThisChat: true
		})
	).toBe(false);
});

test('another app tab does not also play the chime', () => {
	expect(
		shouldPlayCompletionSound({
			soundEnabled: true,
			isLastActiveTab: false,
			hasBeenActive: true,
			focusedOnThisChat: false
		})
	).toBe(false);
});
