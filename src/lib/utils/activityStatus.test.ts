import { describe, expect, it } from 'vitest';
import { endsWithActivity, isInlineStatus } from './activityStatus';

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
