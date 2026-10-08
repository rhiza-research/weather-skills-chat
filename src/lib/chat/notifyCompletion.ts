export function shouldPlayCompletionSound(opts: {
	soundEnabled?: boolean;
	isLastActiveTab?: boolean;
	tabVisible: boolean;
	hasBeenActive?: boolean;
}): boolean {
	return Boolean(
		(opts.soundEnabled ?? true) &&
			(opts.isLastActiveTab ?? true) &&
			(opts.hasBeenActive ?? true) &&
			!opts.tabVisible
	);
}
