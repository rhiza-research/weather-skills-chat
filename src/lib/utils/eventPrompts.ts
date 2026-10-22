export type EventPrompt<T> = {
	data: T;
	respond: (value: unknown) => void;
};

/**
 * Confirmation and input prompts from server tools, one dialog at a time.
 *
 * Tools in the same turn run in parallel, so several prompts can arrive
 * before the user answers the first. Each keeps its own callback; the
 * server waits on every one of them.
 */
export const createPromptQueue = <T>() => {
	const pending: EventPrompt<T>[] = [];

	return {
		/** Add a prompt. Returns true when it should be shown now. */
		push(prompt: EventPrompt<T>): boolean {
			pending.push(prompt);
			return pending.length === 1;
		},
		current(): EventPrompt<T> | undefined {
			return pending[0];
		},
		/** Answer the shown prompt and return the next one to show, if any. */
		answer(value: unknown): EventPrompt<T> | undefined {
			pending.shift()?.respond(value);
			return pending[0];
		}
	};
};
