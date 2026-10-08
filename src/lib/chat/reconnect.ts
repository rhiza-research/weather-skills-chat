export async function afterSocketReconnect(hooks: {
	refreshRecent: () => Promise<void>;
	refreshSidebar: () => Promise<void>;
	refreshArtifacts?: () => Promise<void>;
}) {
	await hooks.refreshRecent();
	await hooks.refreshSidebar();
	if (hooks.refreshArtifacts) await hooks.refreshArtifacts();
}

type SidebarRefresh = () => Promise<void>;

let sidebarRefresh: SidebarRefresh | null = null;

export function setSidebarRefresh(fn: SidebarRefresh | null) {
	sidebarRefresh = fn;
}

export async function refreshSidebar() {
	if (sidebarRefresh) await sidebarRefresh();
}
