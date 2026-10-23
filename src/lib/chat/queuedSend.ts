// Up to MAX_QUEUED_SENDS sends per chat, held in the browser and sent one per
// finished reply. Kept in localStorage so they survive switching chats and
// reloading the page.

export const MAX_QUEUED_SENDS = 3;

const key = (chatId: string) => `chat-queued-send-${chatId}`;

// A new chat has no id until its first turn creates it, and a temporary chat
// ('local') is gone once the user leaves it, so neither is stored.
const storable = (chatId: string | null | undefined): chatId is string =>
	!!chatId && chatId !== 'local';

export const readQueuedSends = (chatId: string | null | undefined): string[] => {
	if (!storable(chatId)) return [];
	try {
		const raw = localStorage.getItem(key(chatId));
		const prompts = raw ? JSON.parse(raw)?.prompts : null;
		return Array.isArray(prompts)
			? prompts.filter((p) => typeof p === 'string').slice(0, MAX_QUEUED_SENDS)
			: [];
	} catch {
		return [];
	}
};

export const writeQueuedSends = (chatId: string | null | undefined, prompts: string[]) => {
	if (!storable(chatId)) return;
	try {
		if (prompts.length === 0) localStorage.removeItem(key(chatId));
		else localStorage.setItem(key(chatId), JSON.stringify({ prompts }));
	} catch {
		// Storage full or blocked: the queued sends still live in the open page.
	}
};
