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

export const ORG_USAGE_LIMIT_MESSAGE =
	'This workspace has reached its monthly usage limit.';
export const USER_USAGE_LIMIT_MESSAGE =
	'You have reached your monthly usage limit in this workspace.';

export const isUsageLimitMessage = (text: unknown): boolean =>
	text === ORG_USAGE_LIMIT_MESSAGE || text === USER_USAGE_LIMIT_MESSAGE;

export const formatUsd = (n: number | null | undefined, fallback = '—'): string => {
	if (n == null || Number.isNaN(Number(n))) return fallback;
	return `$${Number(n).toFixed(2)}`;
};

export const formatTokenCount = (n: number | null | undefined): string => {
	if (n == null || Number.isNaN(Number(n))) return '—';
	const value = Number(n);
	if (Math.abs(value) >= 1_000_000) {
		return `${(value / 1_000_000).toFixed(1).replace(/\.0$/, '')}M`;
	}
	if (Math.abs(value) >= 1000) {
		return `${(value / 1000).toFixed(1).replace(/\.0$/, '')}k`;
	}
	return String(Math.round(value));
};

export const tokenUsageLabel = (): string =>
	'Prompt / Completion / Total / Uncached';

export const tokenUsageTooltip = (usage?: {
	prompt_tokens?: number;
	completion_tokens?: number;
	total_tokens?: number;
	uncached_tokens?: number;
} | null): string => {
	const u = usage || {};
	return [
		tokenUsageLabel(),
		`Prompt: ${formatTokenCount(u.prompt_tokens)}`,
		`Completion: ${formatTokenCount(u.completion_tokens)}`,
		`Total: ${formatTokenCount(u.total_tokens)}`,
		`Uncached: ${formatTokenCount(u.uncached_tokens)}`
	].join('<br>');
};

export const remainingUsd = (
	limit: number | null | undefined,
	used: number | null | undefined
): number | null => {
	if (limit == null || Number.isNaN(Number(limit))) return null;
	return Math.max(0, Number(limit) - Number(used || 0));
};

export const usageBarPercent = (
	spend: number | null | undefined,
	cap: number | null | undefined,
	overLimit = false
): number => {
	if (overLimit) return 100;
	if (cap == null || Number.isNaN(Number(cap))) return 0;
	if (Number(cap) <= 0) return 100;
	return Math.min(100, Math.max(0, (Number(spend || 0) / Number(cap)) * 100));
};
