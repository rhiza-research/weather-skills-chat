export type ChatScroll = {
	top: number;
	atBottom: boolean;
	messagesCount: number;
};

const chatScroll = new Map<string, ChatScroll>();

export const chatScrollFor = (id: string): ChatScroll | null => chatScroll.get(id) ?? null;

export const rememberChatScroll = (id: string, value: ChatScroll) => {
	if (!id) return;
	chatScroll.set(id, value);
};

export const rememberMessageCount = (id: string, messagesCount: number) => {
	if (!id) return;
	const existing = chatScroll.get(id);
	if (existing) {
		existing.messagesCount = messagesCount;
		return;
	}
	chatScroll.set(id, { top: 0, atBottom: true, messagesCount });
};
