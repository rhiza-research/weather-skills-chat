/**
 * Parse a failed fetch Response into a stable error object.
 * Gateways (nginx) often return HTML for 413/502/504; callers historically
 * did `throw await res.json()` which surfaced as "Unexpected token '<'".
 */

export const CHAT_CONFLICT_MESSAGE =
	'Another user has edited the chat. Please try again.';
export const CHAT_BUSY_MESSAGE =
	'This chat is being edited in another window. Please try again shortly.';

function conflictMessage(raw: unknown): string {
	if (typeof raw === 'string') {
		const trimmed = raw.trim();
		if (/another (user|window)/i.test(trimmed)) return trimmed;
		if (/being edited/i.test(trimmed)) return trimmed;
	}
	return CHAT_CONFLICT_MESSAGE;
}

function revisionOf(value: unknown): number | undefined {
	if (value == null) return undefined;
	if (typeof value === 'number' && Number.isFinite(value)) return value;
	if (typeof value === 'string' && value.trim() && Number.isFinite(Number(value))) {
		return Number(value);
	}
	return undefined;
}

export async function parseApiError(
	res: Response
): Promise<{ detail: string; status: number; revision?: number; [key: string]: unknown }> {
	const status = res.status;
	let body = '';
	try {
		body = await res.text();
	} catch {
		body = '';
	}

	const trimmed = body.trimStart();
	const looksJson =
		trimmed.startsWith('{') ||
		trimmed.startsWith('[') ||
		(res.headers.get('content-type') || '').includes('json');

	if (looksJson && trimmed) {
		try {
			const data = JSON.parse(trimmed);
			if (data && typeof data === 'object' && !Array.isArray(data)) {
				const nested = data.detail && typeof data.detail === 'object' && !Array.isArray(data.detail)
					? data.detail
					: null;
				const revision =
					revisionOf(data.revision) ??
					revisionOf(nested?.revision);
				if (status === 409) {
					const raw =
						typeof data.detail === 'string'
							? data.detail
							: typeof nested?.message === 'string'
								? nested.message
								: typeof data.message === 'string'
									? data.message
									: '';
					return { ...data, detail: conflictMessage(raw), revision, status };
				}
				if (typeof data.detail === 'string' || Array.isArray(data.detail)) {
					return { ...data, status, revision };
				}
				if (nested) {
					const message =
						typeof nested.message === 'string' ? nested.message : JSON.stringify(data.detail);
					return { ...data, detail: message, status, revision };
				}
				if (data.error != null) {
					return { ...data, status, revision };
				}
				if (typeof data.message === 'string') {
					return { ...data, detail: data.message, status, revision };
				}
				return { ...data, detail: JSON.stringify(data), status, revision };
			}
			if (typeof data === 'string') {
				return { detail: status === 409 ? conflictMessage(data) : data, status };
			}
			return { detail: JSON.stringify(data), status };
		} catch {
			// fall through to HTML / text handling
		}
	}

	if (status === 409) {
		return { detail: CHAT_CONFLICT_MESSAGE, status };
	}

	const statusHints: Record<number, string> = {
		401: 'Unauthorized — please sign in again.',
		403: 'Forbidden — you do not have permission for this action.',
		404: 'Not found.',
		413: 'Request too large. This chat may have grown too big to save — try a new chat or remove large tool outputs.',
		502: 'Bad gateway — the server or proxy is temporarily unavailable.',
		503: 'Service unavailable — the server is temporarily overloaded.',
		504: 'Gateway timeout — the request took too long.'
	};

	const title = body.match(/<title[^>]*>([^<]+)<\/title>/i)?.[1]?.trim();
	const heading = body.match(/<h1[^>]*>([^<]+)<\/h1>/i)?.[1]?.trim();
	const extracted = (title || heading || '').replace(/\s+/g, ' ');

	if (status === 413 || /request entity too large/i.test(extracted) || /413/.test(extracted)) {
		return { detail: statusHints[413], status };
	}

	if (statusHints[status]) {
		return { detail: statusHints[status], status };
	}

	if (extracted) {
		return { detail: extracted, status };
	}

	if (body && !body.includes('<')) {
		return { detail: body.slice(0, 300), status };
	}

	return { detail: `Request failed with status ${status}`, status };
}
