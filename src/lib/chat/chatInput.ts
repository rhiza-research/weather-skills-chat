/** What the chat bar holds for one chat: the draft and the switches next to it. */
export type ChatInput = {
	prompt: string;
	files: any[];
	selectedToolIds: string[];
	imageGenerationEnabled: boolean;
	webSearchEnabled: boolean;
	codeInterpreterEnabled: boolean;
	readArtifactsEnabled: boolean;
	builtinFeatures: Record<string, boolean>;
};

export const emptyChatInput = (): ChatInput => ({
	prompt: '',
	files: [],
	selectedToolIds: [],
	imageGenerationEnabled: false,
	webSearchEnabled: false,
	codeInterpreterEnabled: false,
	readArtifactsEnabled: false,
	builtinFeatures: {}
});

/** A saved chat bar, or an empty one when nothing (or something unreadable) is saved. */
export const parseChatInput = (raw: string | null): ChatInput => {
	const input = emptyChatInput();
	try {
		const saved = JSON.parse(raw ?? 'null');
		if (saved && typeof saved === 'object') {
			for (const key of Object.keys(input)) {
				if (saved[key] != null) input[key] = saved[key];
			}
		}
	} catch {
		// Unreadable: start empty.
	}
	return input;
};

/** Whether the chat bar differs from an empty one, so it is worth keeping. */
export const chatInputWorthSaving = (input: ChatInput): boolean =>
	!!input.prompt ||
	(input.files?.length ?? 0) > 0 ||
	(input.selectedToolIds?.length ?? 0) > 0 ||
	input.imageGenerationEnabled ||
	input.webSearchEnabled ||
	input.codeInterpreterEnabled ||
	input.readArtifactsEnabled ||
	Object.keys(input.builtinFeatures ?? {}).length > 0;
