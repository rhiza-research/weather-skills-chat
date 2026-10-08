export function shouldPlayCompletionSound(opts: {
	soundEnabled?: boolean;
	isLastActiveTab?: boolean;
	hasBeenActive?: boolean;
	/** True when the user is looking at the chat that just finished. */
	focusedOnThisChat: boolean;
}): boolean {
	return Boolean(
		(opts.soundEnabled ?? true) &&
			(opts.isLastActiveTab ?? true) &&
			(opts.hasBeenActive ?? true) &&
			!opts.focusedOnThisChat
	);
}
