/** Who may change a scheduled task, mirroring can_manage_automation on the server. */
export const canManageTask = (
	task: { user_id: string; visibility?: string } | null,
	userId: string | undefined,
	orgRole: string | undefined
): boolean => {
	if (!task) return true;
	if (task.user_id === userId) return true;
	return task.visibility === 'organization' && (orgRole === 'owner' || orgRole === 'admin');
};

/** A new task's fields from a chat: its title, user turns, model, and tool choices. */
export const taskFromChat = (chatId: string, chat) => {
	const messages = chat?.chat?.messages ?? [];
	const userTurns = messages
		.filter((m) => m.role === 'user')
		.map((m) => m.content)
		.filter(Boolean);
	let tool_ids = null;
	let features = null;
	try {
		const input = JSON.parse(localStorage.getItem(`chat-input-${chatId}`) ?? 'null');
		if (input) {
			tool_ids = Array.isArray(input.selectedToolIds)
				? input.selectedToolIds.filter(Boolean)
				: null;
			features = {
				web_search: !!input.webSearchEnabled,
				code_interpreter: !!input.codeInterpreterEnabled
			};
		}
	} catch {
		// No saved chat input: the task starts with a new chat's tools.
	}
	return {
		name: chat?.title || 'Scheduled chat',
		prompt: userTurns.join('\n\n') || chat?.title || '',
		model: chat?.chat?.models?.[0] || '',
		source_chat_id: chatId,
		visibility: chat?.visibility ?? 'private',
		tool_ids,
		features
	};
};
