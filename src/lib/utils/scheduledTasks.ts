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
				image_generation: !!input.imageGenerationEnabled,
				code_interpreter: !!input.codeInterpreterEnabled,
				...(input.builtinFeatures ?? {})
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

type TaskRun = {
	id: string;
	status: string;
	started_at?: number | null;
	finished_at?: number | null;
};

type SidebarTask = {
	id: string;
	name: string;
	created_at: number;
	seen_run_id?: string | null;
	last_run?: TaskRun | null;
};

/** A finished run older than this gets no dot, seen or not. */
export const DOT_MAX_AGE_S = 7 * 24 * 60 * 60;

export type TaskDot = 'running' | 'success' | 'failure' | 'unknown' | 'error';

/** The dot beside a task in the sidebar, or null for none. */
export const taskDot = (task: SidebarTask, now = Date.now() / 1000): TaskDot | null => {
	const run = task.last_run;
	if (!run) return null;
	if (run.status === 'running') return 'running';
	if (run.id === task.seen_run_id) return null;
	const ended = run.finished_at ?? run.started_at ?? 0;
	if (now - ended > DOT_MAX_AGE_S) return null;
	return ['success', 'failure', 'unknown', 'error'].includes(run.status)
		? (run.status as TaskDot)
		: null;
};

export type TaskSort = 'recent' | 'name' | 'created';

export const sortTasks = <T extends SidebarTask>(tasks: T[], by: TaskSort): T[] => {
	const byName = (a: T, b: T) => a.name.localeCompare(b.name);
	const sorted = [...tasks];
	if (by === 'name') return sorted.sort(byName);
	if (by === 'created') return sorted.sort((a, b) => b.created_at - a.created_at || byName(a, b));
	return sorted.sort(
		(a, b) =>
			(b.last_run?.started_at ?? -1) - (a.last_run?.started_at ?? -1) || byName(a, b)
	);
};
