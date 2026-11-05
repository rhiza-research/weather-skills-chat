// Where a live status line is drawn, so it appears exactly once.
//
// These statuses are plain progress lines. When a message ends with an
// activity row (thinking or tool calls), that row shows the status as its
// headline. Otherwise the line under the message shows it, below any text the
// model has written since the last activity row.

export const INLINE_STATUS_ACTIONS = new Set([
	'waiting_response',
	'weather_skills_runner',
	'preparing_tool_calls'
]);

export const isInlineStatus = (status: { action?: string } | null | undefined): boolean =>
	INLINE_STATUS_ACTIONS.has(String(status?.action ?? ''));

/** True when the message's last block is an activity row: a <details> block
 * other than code_interpreter, with nothing but whitespace after it. */
export const endsWithActivity = (content: string | null | undefined): boolean => {
	const text = String(content ?? '').trimEnd();
	if (!text.endsWith('</details>')) return false;
	const open = text.lastIndexOf('<details');
	if (open < 0) return false;
	const tagEnd = text.indexOf('>', open);
	const tag = tagEnd < 0 ? text.slice(open) : text.slice(open, tagEnd);
	return !/type="code_interpreter"/.test(tag);
};

const ACTIVITY_TYPES = new Set(['reasoning', 'tool_calls', 'code_interpreter']);

const isOpenActivity = (token: any) =>
	token?.type === 'details' &&
	ACTIVITY_TYPES.has(token?.attributes?.type) &&
	token?.attributes?.done !== 'true';

/** Marked tokens with every open activity block shown as done once something
 * else follows it: text, or a block of another type. Open tool calls in a row
 * stay open, since a batch of calls runs at the same time. */
export const settleFollowedActivity = (tokens: any[]): any[] => {
	if (!tokens?.length) return tokens;
	const laterTypes = new Set<string>();
	const out = [...tokens];
	for (let i = out.length - 1; i >= 0; i--) {
		const token = out[i];
		if (!String(token?.raw ?? '').trim()) continue;
		const type = token?.type === 'details' ? token?.attributes?.type : token?.type;
		if (isOpenActivity(token) && [...laterTypes].some((t) => t !== type)) {
			out[i] = { ...token, attributes: { ...token.attributes, done: 'true' } };
		}
		laterTypes.add(type);
	}
	return out;
};
