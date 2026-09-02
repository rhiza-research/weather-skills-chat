/**
 * Parse a failed fetch Response into a stable error object.
 * Gateways (nginx) often return HTML for 413/502/504; callers historically
 * did `throw await res.json()` which surfaced as "Unexpected token '<'".
 */
export async function parseApiError(
	res: Response
): Promise<{ detail: string; status: number; [key: string]: unknown }> {
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
				if (typeof data.detail === 'string' || Array.isArray(data.detail)) {
					return { ...data, status };
				}
				if (data.error != null) {
					return { ...data, status };
				}
				if (typeof data.message === 'string') {
					return { ...data, detail: data.message, status };
				}
				return { ...data, detail: JSON.stringify(data), status };
			}
			if (typeof data === 'string') {
				return { detail: data, status };
			}
			return { detail: JSON.stringify(data), status };
		} catch {
			// fall through to HTML / text handling
		}
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
