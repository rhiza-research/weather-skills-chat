import { describe, expect, it, vi } from 'vitest';
import { createPromptQueue } from './eventPrompts';

describe('createPromptQueue', () => {
	it('answers each prompt with its own callback, in arrival order', () => {
		const queue = createPromptQueue<string>();
		const first = vi.fn();
		const second = vi.fn();

		expect(queue.push({ data: 'a.png', respond: first })).toBe(true);
		expect(queue.push({ data: 'b.csv', respond: second })).toBe(false);
		expect(queue.current()?.data).toBe('a.png');

		expect(queue.answer(true)?.data).toBe('b.csv');
		expect(first).toHaveBeenCalledWith(true);
		expect(second).not.toHaveBeenCalled();

		expect(queue.answer(false)).toBeUndefined();
		expect(second).toHaveBeenCalledWith(false);
		expect(first).toHaveBeenCalledTimes(1);
	});

	it('shows a prompt that arrives after the queue drains', () => {
		const queue = createPromptQueue<string>();
		queue.push({ data: 'a.png', respond: vi.fn() });
		queue.answer(true);
		expect(queue.push({ data: 'b.csv', respond: vi.fn() })).toBe(true);
	});

	it('ignores an answer when nothing is pending', () => {
		const queue = createPromptQueue<string>();
		expect(queue.answer(true)).toBeUndefined();
	});
});
