/** Status action emitted by the server for dead-generation detection. */
export const GENERATION_HEARTBEAT_ACTION = 'generation_heartbeat';

export const GENERATION_LOST_MESSAGE =
	'Connection to the server was lost. You can retry — the model will continue from any tools or artifacts that already completed.';

export const SERVER_UNREACHABLE_MESSAGE = 'Failed to reach the server.';

/** Detect browser/network failures when the backend is down or unreachable. */
export const isServerUnreachableError = (error: unknown): boolean => {
	const text =
		typeof error === 'string'
			? error
			: typeof (error as { message?: unknown })?.message === 'string'
				? (error as { message: string }).message
				: String(error ?? '');
	const lower = text.toLowerCase();
	return (
		lower.includes('failed to fetch') ||
		lower.includes('networkerror') ||
		lower.includes('network request failed') ||
		lower.includes('load failed') ||
		lower.includes('fetch failed')
	);
};

export const formatGenerationRequestError = (error: unknown): string => {
	if (isServerUnreachableError(error)) {
		return SERVER_UNREACHABLE_MESSAGE;
	}
	if (typeof error === 'string') {
		return error;
	}
	const detail = (error as { detail?: unknown })?.detail;
	if (typeof detail === 'string') {
		return detail;
	}
	const message = (error as { message?: unknown })?.message;
	if (typeof message === 'string' && message.trim()) {
		return message;
	}
	return String(error ?? 'Unknown error');
};

/** Mark incomplete tool/reasoning/code details as done so spinners stop. */
export const clearSpinningToolCalls = (content: string) => {
	if (typeof content !== 'string') {
		return content;
	}
	return content.replace(
		/(<details type="(?:tool_calls|reasoning|code_interpreter)" )done="false"/g,
		'$1done="true"'
	);
};

/**
 * Mark incomplete assistant messages as failed when no server task is live.
 * Returns how many messages were finalized.
 */
export const finalizeOrphanAssistantMessages = (
	messages: Record<string, any>,
	hasLiveTask: boolean,
	reason: string = GENERATION_LOST_MESSAGE
): number => {
	if (hasLiveTask) {
		return 0;
	}
	let count = 0;
	for (const message of Object.values(messages || {})) {
		if (!message || message.role !== 'assistant') continue;
		if (message.done === true) continue;
		message.error = message.error ?? { content: reason };
		message.done = true;
		message.content = clearSpinningToolCalls(message.content ?? '');
		count += 1;
	}
	return count;
};
