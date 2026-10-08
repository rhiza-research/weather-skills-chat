export function shouldPersistHistory(
	temporaryChatEnabled: boolean,
	chatId?: string | null
): boolean {
	return !temporaryChatEnabled && !!chatId && chatId !== 'local';
}
