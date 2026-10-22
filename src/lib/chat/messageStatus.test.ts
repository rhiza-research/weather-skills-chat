import { describe, expect, it } from 'vitest';

import { shownStatus } from './messageStatus';

const preparing = { action: 'preparing_tool_calls', description: 'Preparing tool calls… (0s)', done: false };

describe('shownStatus', () => {
	it('keeps a running reply’s open status', () => {
		expect(shownStatus({ done: false, statusHistory: [preparing] })).toEqual(preparing);
	});

	it('hides an open status on a finished reply', () => {
		expect(shownStatus({ done: true, statusHistory: [preparing] })).toEqual({
			...preparing,
			done: true,
			hidden: true
		});
		expect(shownStatus({ done: true, status: preparing })?.hidden).toBe(true);
	});

	it('leaves closed statuses alone', () => {
		const searched = { action: 'web_search', description: 'Searched 3 sites', done: true };
		expect(shownStatus({ done: true, statusHistory: [preparing, searched] })).toEqual(searched);
	});

	it('is null without a status', () => {
		expect(shownStatus({ done: true })).toBeNull();
		expect(shownStatus(null)).toBeNull();
	});
});
