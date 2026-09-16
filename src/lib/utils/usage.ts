/** Keys that should be added across LLM turns in a single assistant message. */
const SUMMABLE_KEY = /token|cost/i;

function cloneJson<T>(value: T): T {
	return value == null ? value : JSON.parse(JSON.stringify(value));
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
	return !!value && typeof value === 'object' && !Array.isArray(value);
}

/**
 * Merge a new usage payload into the running totals for one assistant message.
 * Numeric token/cost fields (including nested details) are summed; other fields
 * keep the latest value. Used so the info popup shows the whole tool loop until
 * stop, not only the last turn.
 */
export function accumulateUsage(existing: unknown, incoming: unknown): unknown {
	if (incoming == null) {
		return existing;
	}
	if (existing == null) {
		return cloneJson(incoming);
	}
	if (typeof incoming === 'number' && Number.isFinite(incoming)) {
		return (typeof existing === 'number' && Number.isFinite(existing) ? existing : 0) + incoming;
	}
	if (!isPlainObject(incoming)) {
		return cloneJson(incoming);
	}

	const out: Record<string, unknown> = isPlainObject(existing) ? { ...existing } : {};
	for (const [key, value] of Object.entries(incoming)) {
		if (isPlainObject(value)) {
			out[key] = accumulateUsage(out[key], value);
			continue;
		}
		if (typeof value === 'number' && Number.isFinite(value) && SUMMABLE_KEY.test(key)) {
			const prev = out[key];
			out[key] = (typeof prev === 'number' && Number.isFinite(prev) ? prev : 0) + value;
			continue;
		}
		out[key] = cloneJson(value);
	}
	return out;
}
