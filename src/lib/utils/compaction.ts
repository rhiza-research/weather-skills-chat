/** Matches the server's limit on the summary call. */
export const COMPACTION_TIMEOUT_MS = 90_000;

export type Compaction = {
	status?: string;
	started_at?: number;
	summary?: string;
	context_estimate?: number;
	context_window?: number;
};

/** A compaction still running; one older than the timeout died with its server. */
export const compactionRunning = (compaction: Compaction | null | undefined, nowMs = Date.now()) =>
	compaction?.status === 'running' &&
	typeof compaction.started_at === 'number' &&
	nowMs - compaction.started_at * 1000 < COMPACTION_TIMEOUT_MS;

/** When a running compaction counts as failed, in ms since the epoch. */
export const compactionExpiresAt = (compaction: Compaction) =>
	(compaction.started_at ?? 0) * 1000 + COMPACTION_TIMEOUT_MS;

function* branch(history: any) {
	const seen = new Set<string>();
	for (
		let message = history?.messages?.[history?.currentId];
		message && !seen.has(message.id);
		message = history.messages[message.parentId]
	) {
		seen.add(message.id);
		yield message;
	}
}

/** The running compaction on the open branch, if any. */
export const runningCompaction = (history: any, nowMs = Date.now()): Compaction | null => {
	for (const message of branch(history)) {
		if (compactionRunning(message.compaction, nowMs)) return message.compaction;
	}
	return null;
};

/**
 * How full the model's context is: the latest real count on the branch, or the
 * estimate a compaction made until the next reply reports a real one.
 */
export const contextShown = (
	history: any
): { used: number; window: number; estimate: boolean } | null => {
	for (const message of branch(history)) {
		const compaction = message.compaction;
		if (
			compaction?.status === 'done' &&
			typeof compaction.context_estimate === 'number' &&
			compaction.context_window
		) {
			return {
				used: compaction.context_estimate,
				window: compaction.context_window,
				estimate: true
			};
		}
		if (message.usage?.context_window) {
			return {
				used: message.usage.context_used,
				window: message.usage.context_window,
				estimate: false
			};
		}
	}
	return null;
};
