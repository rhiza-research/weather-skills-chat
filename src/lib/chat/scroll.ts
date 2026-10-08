export type ChatScroll = {
	top: number;
	atBottom: boolean;
	messagesCount: number;
	unseen?: boolean;
	/** Message sitting at the bottom of the screen when scrolling stopped. */
	messageId?: string;
	/** That message's top, relative to the top of the message pane. */
	messageOffset?: number;
	/** img alt, or a snippet of the text line, at the top of the pane. */
	anchorKind?: 'img' | 'text';
	anchorKey?: string;
	/** Which copy, when the same image or line is repeated. */
	anchorIndex?: number;
	/** That line's top, relative to the top of the message pane. */
	anchorOffset?: number;
};

const chatScroll = new Map<string, ChatScroll>();
const tailListeners = new Set<(id: string) => void>();

export const chatScrollFor = (id: string): ChatScroll | null => chatScroll.get(id) ?? null;

export const rememberChatScroll = (id: string, value: ChatScroll) => {
	if (!id) return;
	chatScroll.set(id, value);
};

/** A reply arrived below a saved position that is not the bottom. */
export const markUnseenMessages = (id: string) => {
	if (!id) return;
	const existing = chatScroll.get(id);
	if (!existing || existing.atBottom) return;
	existing.unseen = true;
};

/** Drop the saved position so the next open lands on the new message. */
export const requestChatTail = (id: string) => {
	if (!id) return;
	const existing = chatScroll.get(id);
	chatScroll.set(id, {
		top: 0,
		atBottom: true,
		messagesCount: existing?.messagesCount ?? 20,
		unseen: false
	});
	for (const listener of tailListeners) listener(id);
};

export const onChatTailRequest = (listener: (id: string) => void) => {
	tailListeners.add(listener);
	return () => tailListeners.delete(listener);
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
