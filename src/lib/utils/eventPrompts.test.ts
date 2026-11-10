import { get } from 'svelte/store';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { addEventPrompt, answerEventPrompt, eventPrompts, nextEventPrompt } from './eventPrompts';

const prompt = (chatId: string, path: string) => ({
	chatId,
	data: { path },
	respond: vi.fn()
});

describe('eventPrompts', () => {
	beforeEach(() => eventPrompts.set([]));

	it('answers each prompt with its own callback, in arrival order', () => {
		const first = prompt('a', 'a.png');
		const second = prompt('a', 'b.csv');
		addEventPrompt(first);
		addEventPrompt(second);
		expect(nextEventPrompt(get(eventPrompts), 'a')).toBe(first);

		answerEventPrompt(first, true);
		expect(first.respond).toHaveBeenCalledWith(true);
		expect(second.respond).not.toHaveBeenCalled();
		expect(nextEventPrompt(get(eventPrompts), 'a')).toBe(second);

		answerEventPrompt(second, 'this_file');
		expect(second.respond).toHaveBeenCalledWith('this_file');
		expect(nextEventPrompt(get(eventPrompts), 'a')).toBeNull();
	});

	it('keeps another chat’s prompt until that chat is open', () => {
		const other = prompt('b', 'x.png');
		addEventPrompt(other);
		expect(nextEventPrompt(get(eventPrompts), 'a')).toBeNull();
		expect(nextEventPrompt(get(eventPrompts), 'b')).toBe(other);
	});

	it('answers a prompt only once', () => {
		const only = prompt('a', 'a.png');
		addEventPrompt(only);
		answerEventPrompt(only, true);
		answerEventPrompt(only, false);
		expect(only.respond).toHaveBeenCalledTimes(1);
	});
});
