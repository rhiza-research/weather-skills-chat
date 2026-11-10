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

type SidebarRefresh = () => Promise<void>;

let sidebarRefresh: SidebarRefresh | null = null;

export function setSidebarRefresh(fn: SidebarRefresh | null) {
	sidebarRefresh = fn;
}

export async function refreshSidebar() {
	if (sidebarRefresh) await sidebarRefresh();
}
