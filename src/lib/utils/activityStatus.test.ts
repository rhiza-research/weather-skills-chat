import { describe, expect, it } from 'vitest';
import { Marked } from 'marked';
import markedExtension from '$lib/utils/marked/extension';
import { endsWithActivity, isInlineStatus, settleFollowedActivity } from './activityStatus';

const thinking = '<details type="reasoning" done="true" duration="4">\n<summary>Thought</summary>\n</details>';
const tools = '<details type="tool_calls" done="true" id="a" name="fetch">\n</details>';

describe('endsWithActivity', () => {
	it('is true when the message ends with thinking or tool calls', () => {
		expect(endsWithActivity(thinking)).toBe(true);
		expect(endsWithActivity(`${tools}\n\n`)).toBe(true);
		expect(endsWithActivity(`Some text\n\n${tools}`)).toBe(true);
	});

	it('is false when text follows the last activity row', () => {
		expect(endsWithActivity(`${tools}\n\nFetching the other 9 octobers in parallel.`)).toBe(false);
		expect(endsWithActivity('Just text')).toBe(false);
		expect(endsWithActivity('')).toBe(false);
		expect(endsWithActivity(null)).toBe(false);
	});

	it('does not count a code interpreter block', () => {
		expect(endsWithActivity('<details type="code_interpreter" done="true">\n</details>')).toBe(false);
	});
});

describe('isInlineStatus', () => {
	it('covers the plain progress lines only', () => {
		expect(isInlineStatus({ action: 'preparing_tool_calls' })).toBe(true);
		expect(isInlineStatus({ action: 'waiting_response' })).toBe(true);
		expect(isInlineStatus({ action: 'weather_skills_runner' })).toBe(true);
		expect(isInlineStatus({ action: 'web_search' })).toBe(false);
		expect(isInlineStatus(null)).toBe(false);
	});
});

describe('settleFollowedActivity', () => {
	const lex = (content: string) => {
		const md = new Marked();
		md.use(markedExtension({}));
		return md.lexer(content);
	};
	const open = (type: string, id = '') =>
		`<details type="${type}" done="false"${id ? ` id="${id}"` : ''}>\n<summary>…</summary>\n</details>`;
	const doneFlags = (content: string) =>
		settleFollowedActivity(lex(content))
			.filter((t) => t.type === 'details')
			.map((t) => t.attributes.done);

	it('shows an open block as done once text follows it', () => {
		expect(doneFlags(`${open('reasoning')}\n\nThe answer is 4.`)).toEqual(['true']);
		expect(doneFlags(`${open('tool_calls', 'a')}\n\nDone.`)).toEqual(['true']);
	});

	it('shows open thinking as done once tool calls follow it', () => {
		expect(doneFlags(`${open('reasoning')}\n${open('tool_calls', 'a')}`)).toEqual(['true', 'false']);
	});

	it('keeps the last open block and a batch of open tool calls open', () => {
		expect(doneFlags(`Hi\n\n${open('reasoning')}`)).toEqual(['false']);
		expect(doneFlags(`${open('tool_calls', 'a')}\n${open('tool_calls', 'b')}`)).toEqual(['false', 'false']);
	});
});
