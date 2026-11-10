import { get } from 'svelte/store';
import { getModels } from '$lib/apis';
import { getToolSummary } from '$lib/apis/tools';
import {
	activeOrganizationId,
	models,
	organizations,
	switchingOrganization,
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

/** The user's platform membership when it makes them a platform admin. */
export const platformAdminMembership = (
	memberships: Parameters<typeof isPlatformAdminContext>[0][] | null
) => (memberships ?? []).find((org) => isPlatformAdminContext(org)) ?? null;

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

/** Models and tools for the active org. Does not read settings or config. */
export const loadOrganizationCatalog = (token: string) =>
	Promise.all([getModels(token), getToolSummary(token)]);

/** Reload catalogs that depend on the active org and effective role. */
export const reloadOrganizationCatalog = async (token: string) => {
	applyContextUserRole();
	const [nextModels, nextTools] = await loadOrganizationCatalog(token);
	await models.set(nextModels);
	await tools.set(nextTools);
};

/**
 * Make `orgId` the active organization and load its catalog, then run `then`.
 * Does nothing for an organization the user is not a member of, the active one,
 * or while another switch runs. On failure the previous organization comes back
 * and the error is rethrown. Returns whether it switched.
 */
export const switchOrganization = async (
	orgId: string | null | undefined,
	token: string,
	then: () => Promise<unknown> = async () => {}
) => {
	const previousId = get(activeOrganizationId);
	if (
		!orgId ||
		orgId === previousId ||
		get(switchingOrganization) ||
		!(get(organizations) ?? []).some((org) => org.id === orgId)
	) {
		return false;
	}
	switchingOrganization.set(true);
	activeOrganizationId.set(orgId);
	try {
		await reloadOrganizationCatalog(token);
		await then();
		return true;
	} catch (error) {
		activeOrganizationId.set(previousId);
		await reloadOrganizationCatalog(token).catch(console.error);
		throw error;
	} finally {
		switchingOrganization.set(false);
	}
};

/**
 * After accepting an invitation to an organization, open the app in it.
 *
 * The membership list loaded before accepting does not have the new
 * organization yet, and the app falls back to the personal organization when
 * the active one is not in the list, so the list is cleared for the app to
 * reload. A platform invitation has no organization and changes nothing.
 */
export const openInvitedOrganization = (
	organizationId: string | null | undefined,
	storage: Pick<Storage, 'setItem'> = localStorage
) => {
	if (!organizationId) return;
	organizations.set(null);
	activeOrganizationId.set(organizationId);
	storage.setItem('activeOrganizationId', organizationId);
};
