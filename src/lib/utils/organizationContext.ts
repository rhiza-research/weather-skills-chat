import { get } from 'svelte/store';
import { getModels } from '$lib/apis';
import { getTools } from '$lib/apis/tools';
import {
	activeOrganizationId,
	config,
	models,
	organizations,
	settings,
	tools,
	user
} from '$lib/stores';

export const currentOrganization = () => {
	const session = get(user);
	const orgId = get(activeOrganizationId);
	return (
		(get(organizations) ?? []).find((item) => item.id === orgId) ?? {
			id: session?.id,
			name: 'Personal',
			kind: 'personal',
			role: 'owner'
		}
	);
};

export const isPlatformAdminContext = (org = currentOrganization()) =>
	org?.kind === 'platform' && (org.role === 'owner' || org.role === 'admin');

export const isWorkspaceManagerContext = (org = currentOrganization()) =>
	org?.kind === 'workspace' && (org.role === 'owner' || org.role === 'admin');

export const applyContextUserRole = () => {
	const session = get(user);
	if (!session || session.role === 'pending') {
		return;
	}
	const org = currentOrganization();
	const nextRole = isPlatformAdminContext(org) ? 'admin' : 'user';
	if (session.role !== nextRole) {
		user.set({ ...session, role: nextRole });
	}
};

/** Reload catalogs that depend on the active org and effective role. */
export const reloadOrganizationCatalog = async (token: string) => {
	applyContextUserRole();
	const cfg = get(config);
	const ui = get(settings);
	const [nextModels, nextTools] = await Promise.all([
		getModels(
			token,
			cfg?.features?.enable_direct_connections && (ui?.directConnections ?? null)
		),
		getTools(token)
	]);
	await models.set(nextModels);
	await tools.set(nextTools);
};
