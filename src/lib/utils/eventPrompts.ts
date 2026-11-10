import { writable } from 'svelte/store';

export type EventPrompt = {
	/** The chat whose reply asked. */
	chatId: string;
	data: Record<string, any>;
	respond: (value: unknown) => void;
};

/**
 * Confirmation and input prompts from server tools that wait for an answer,
 * oldest first, for every chat.
 *
 * Tools in the same turn run in parallel, so several prompts can arrive
 * before the user answers the first. Each keeps its own callback; the
 * server waits on every one of them. A prompt for a chat the user is not
 * looking at waits here until they open that chat.
 */
export const eventPrompts = writable<EventPrompt[]>([]);

export const addEventPrompt = (prompt: EventPrompt) =>
	eventPrompts.update((list) => [...list, prompt]);

/** Answer a prompt once; a second answer to the same prompt is ignored. */
export const answerEventPrompt = (prompt: EventPrompt, value: unknown) => {
	let pending = false;
	eventPrompts.update((list) => {
		pending = list.includes(prompt);
		return list.filter((p) => p !== prompt);
	});
	if (pending) prompt.respond(value);
};

/** The prompt to show in this chat, if any. */
export const nextEventPrompt = (list: EventPrompt[], chatId: string) =>
	list.find((p) => p.chatId === chatId) ?? null;
