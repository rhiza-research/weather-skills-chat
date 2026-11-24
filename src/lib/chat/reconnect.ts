export async function afterSocketReconnect(hooks: {
	refreshRecent: () => Promise<void>;
	refreshSidebar: () => Promise<void>;
	refreshArtifacts?: () => Promise<void>;
	refreshScheduledTasks?: () => Promise<void>;
}) {
	await hooks.refreshRecent();
	await hooks.refreshSidebar();
	if (hooks.refreshArtifacts) await hooks.refreshArtifacts();
	// Run events missed while offline would leave a task's dot on an older run.
	if (hooks.refreshScheduledTasks) await hooks.refreshScheduledTasks();
}

// full also reloads folders, pinned chats and tags, and drops deleted chats.
type SidebarRefresh = (full?: boolean) => Promise<void>;

let sidebarRefresh: SidebarRefresh | null = null;

export function setSidebarRefresh(fn: SidebarRefresh | null) {
	sidebarRefresh = fn;
}

export async function refreshSidebar(full = false) {
	if (sidebarRefresh) await sidebarRefresh(full);
}
