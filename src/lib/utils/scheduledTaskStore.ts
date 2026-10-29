import { get } from 'svelte/store';
import { activeOrganizationId, scheduledTasks } from '$lib/stores';
import { getAutomations, markAutomationRunSeen, setAutomationPinned } from '$lib/apis/automations';

export const loadScheduledTasks = async (token: string) => {
	const list = await getAutomations(token).catch(() => null);
	if (list) scheduledTasks.set(list);
};

const updateTask = (id: string, change: (task) => object) =>
	scheduledTasks.update((list) =>
		(list ?? []).map((task) => (task.id === id ? { ...task, ...change(task) } : task))
	);

/**
 * An `automation:run` socket event: a run of a task started or ended. A run
 * that ends while its chat is open counts as seen.
 */
export const applyRunEvent = async (token: string, event, openChatId: string) => {
	if (!event?.automation_id || !event?.run) return;
	if (event.organization_id !== get(activeOrganizationId)) return;
	if (!(get(scheduledTasks) ?? []).some((t) => t.id === event.automation_id)) {
		// A task this page has not loaded yet, such as one just created.
		await loadScheduledTasks(token);
	}
	updateTask(event.automation_id, () => ({ last_run: event.run }));
	if (event.run.chat_id && event.run.chat_id === openChatId) {
		const task = (get(scheduledTasks) ?? []).find((t) => t.id === event.automation_id);
		if (task) await markTaskSeen(token, task);
	}
};

/** Clear a task's dot once its finished last run is opened. */
export const markTaskSeen = async (token: string, task) => {
	const run = task?.last_run;
	if (!run || run.status === 'running' || task.seen_run_id === run.id) return;
	updateTask(task.id, () => ({ seen_run_id: run.id }));
	await markAutomationRunSeen(token, task.id, run.id).catch(() => null);
};

export const setTaskPinned = async (token: string, id: string, pinned: boolean) => {
	updateTask(id, () => ({ pinned }));
	await setAutomationPinned(token, id, pinned).catch(() => {
		updateTask(id, () => ({ pinned: !pinned }));
	});
};
