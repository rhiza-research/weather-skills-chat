import { expect, test } from 'vitest';
import { shouldPlayCompletionSound } from './notifyCompletion';

test('a completion chime plays only when this tab is in the background', () => {
	expect(
		shouldPlayCompletionSound({
			soundEnabled: true,
			isLastActiveTab: true,
			tabVisible: false,
			hasBeenActive: true
		})
	).toBe(true);
});

test('a focused tab does not play a completion chime', () => {
	expect(
		shouldPlayCompletionSound({
			soundEnabled: true,
			isLastActiveTab: true,
			tabVisible: true,
			hasBeenActive: true
		})
	).toBe(false);
});

test('another app tab does not also play the chime', () => {
	expect(
		shouldPlayCompletionSound({
			soundEnabled: true,
			isLastActiveTab: false,
			tabVisible: false,
			hasBeenActive: true
		})
	).toBe(false);
});
