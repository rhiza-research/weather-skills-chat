export const CHAT_CONFLICT_MESSAGE = 'Another user has edited the chat. Please try again.';
export const CHAT_BUSY_MESSAGE =
	'This chat is being edited by another window. Please try again shortly.';

export function isChatConflict(error: unknown): boolean {
	const status = (error as { status?: number } | null)?.status;
	return status === 409;
}

export function conflictRevision(error: unknown): number | null {
	const revision = Number((error as { revision?: unknown } | null)?.revision);
	return Number.isFinite(revision) ? revision : null;
}

export async function recoverSendConflict(opts: {
	refetch: () => Promise<unknown>;
	retry: () => Promise<unknown>;
}): Promise<'retried' | 'failed'> {
	try {
		await opts.refetch();
		await opts.retry();
		return 'retried';
	} catch {
		return 'failed';
	}
}

export async function recoverEditConflict(opts: {
	refetch: () => Promise<unknown>;
	reapply: () => Promise<unknown>;
}): Promise<'reapplied' | 'failed'> {
	try {
		await opts.refetch();
		await opts.reapply();
		return 'reapplied';
	} catch {
		return 'failed';
	}
}
