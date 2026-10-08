export const CHAT_CONFLICT_MESSAGE = 'Another user has edited the chat. Please try again.';
export const CHAT_BUSY_MESSAGE =
	'This chat is being edited by another window. Please try again shortly.';

export function isChatBusy(error: unknown): boolean {
	const detail =
		typeof error === 'string'
			? error
			: String((error as { detail?: unknown } | null)?.detail ?? '');
	return /another window/i.test(detail);
}

export function isChatConflict(error: unknown): boolean {
	if (isChatBusy(error)) return false;
	const status = (error as { status?: number } | null)?.status;
	if (status === 409) return true;
	const detail =
		typeof error === 'string'
			? error
			: String((error as { detail?: unknown } | null)?.detail ?? '');
	return /another user has edited the chat/i.test(detail);
}

export function writeErrorMessage(error: unknown): string {
	if (isChatBusy(error)) return CHAT_BUSY_MESSAGE;
	if (isChatConflict(error)) return CHAT_CONFLICT_MESSAGE;
	return '';
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
