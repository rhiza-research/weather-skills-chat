import { get } from 'svelte/store';
import { playingNotificationSound, settings } from '$lib/stores';

let notificationAudio: HTMLAudioElement | null = null;

export function playNotificationSound() {
	if (typeof Audio === 'undefined') return;
	if (!(get(settings)?.notificationSound ?? true)) return;
	if (get(playingNotificationSound)) return;
	const activation = typeof navigator !== 'undefined' ? navigator.userActivation : undefined;
	if (activation && !activation.hasBeenActive) return;

	playingNotificationSound.set(true);
	if (!notificationAudio) {
		notificationAudio = new Audio('/audio/notification.mp3');
		notificationAudio.preload = 'auto';
	}
	notificationAudio.currentTime = 0;
	notificationAudio.play().finally(() => {
		playingNotificationSound.set(false);
	});
}
