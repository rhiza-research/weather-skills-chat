import { get } from 'svelte/store';
import { shouldPlayCompletionSound } from '$lib/chat/notifyCompletion';
import { isLastActiveTab, playingNotificationSound, settings } from '$lib/stores';

const SOUNDS = { reply: '/audio/notification.mp3', approval: '/audio/approval.mp3' };
const audio: Partial<Record<keyof typeof SOUNDS, HTMLAudioElement>> = {};

export function playNotificationSound(opts?: {
	focusedOnThisChat?: boolean;
	/** `approval` when the agent waits for the user to answer a popup. */
	kind?: keyof typeof SOUNDS;
}) {
	const kind = opts?.kind ?? 'reply';
	if (typeof Audio === 'undefined') return;
	if (get(playingNotificationSound)) return;
	const activation = typeof navigator !== 'undefined' ? navigator.userActivation : undefined;
	if (
		!shouldPlayCompletionSound({
			soundEnabled: get(settings)?.notificationSound ?? true,
			// A popup reaches only the tab that sent the message, so that tab plays it.
			isLastActiveTab: kind === 'approval' || get(isLastActiveTab),
			hasBeenActive: !activation || activation.hasBeenActive,
			focusedOnThisChat: opts?.focusedOnThisChat ?? false
		})
	) {
		return;
	}

	playingNotificationSound.set(true);
	const sound = (audio[kind] ??= new Audio(SOUNDS[kind]));
	sound.preload = 'auto';
	sound.currentTime = 0;
	sound.play().finally(() => {
		playingNotificationSound.set(false);
	});
}
