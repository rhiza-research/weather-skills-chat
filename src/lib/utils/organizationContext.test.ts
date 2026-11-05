import { expect, test, vi } from 'vitest';
import { get } from 'svelte/store';
import { activeOrganizationId, models, organizations, switchingOrganization } from '$lib/stores';
import {
	openInvitedOrganization,
	platformAdminMembership,
	switchOrganization
} from './organizationContext';

// Each org's catalog has its own model, so a test can see which org loaded.
const getModels = vi.fn(async () => [{ id: `model-of-${get(activeOrganizationId)}` }]);
vi.mock('$lib/apis', () => ({ getModels: () => getModels() }));
vi.mock('$lib/apis/tools', () => ({ getToolSummary: async () => [] }));

const personal = { id: 'u1', name: 'Personal', kind: 'personal', role: 'owner' };
const workspace = { id: 'w1', name: 'Team', kind: 'workspace', role: 'admin' };

test('platform owners and admins have a platform admin membership', () => {
	for (const role of ['owner', 'admin']) {
		const platform = { id: 'platform', name: 'Platform', kind: 'platform', role };
		expect(platformAdminMembership([personal, workspace, platform])).toBe(platform);
	}
});

test('workspace admins and platform users do not', () => {
	expect(platformAdminMembership([personal, workspace])).toBeNull();
	expect(
		platformAdminMembership([personal, { id: 'platform', name: 'Platform', kind: 'platform', role: 'user' }])
	).toBeNull();
	expect(platformAdminMembership(null)).toBeNull();
});

test('accepting an organization invitation opens that organization', () => {
	const saved = new Map<string, string>();
	const storage = { setItem: (key: string, value: string) => saved.set(key, value) };
	activeOrganizationId.set('u1');
	organizations.set([personal]);

	openInvitedOrganization('w1', storage);

	expect(get(activeOrganizationId)).toBe('w1');
	expect(saved.get('activeOrganizationId')).toBe('w1');
	// The new membership is not in the old list yet, so the list is cleared
	// rather than letting it send the user back to their personal organization.
	expect(get(organizations)).toBeNull();
});

test('a platform invitation leaves the organization alone', () => {
	const saved = new Map<string, string>();
	activeOrganizationId.set('u1');
	openInvitedOrganization(null, { setItem: (k: string, v: string) => saved.set(k, v) });
	expect(get(activeOrganizationId)).toBe('u1');
	expect(saved.size).toBe(0);
});

test("opening a chat from another of the user's orgs switches to it and loads its models", async () => {
	organizations.set([personal, workspace]);
	activeOrganizationId.set('u1');

	expect(await switchOrganization('w1', 'token')).toBe(true);

	expect(get(activeOrganizationId)).toBe('w1');
	expect(get(models)).toEqual([{ id: 'model-of-w1' }]);
	expect(get(switchingOrganization)).toBe(false);
});

test('a chat from an org the user is not in, or the active org, changes nothing', async () => {
	organizations.set([personal, workspace]);
	activeOrganizationId.set('u1');
	getModels.mockClear();

	// Shared chats can come from orgs the user does not belong to.
	expect(await switchOrganization('other-org', 'token')).toBe(false);
	expect(await switchOrganization('u1', 'token')).toBe(false);
	expect(await switchOrganization(null, 'token')).toBe(false);

	expect(get(activeOrganizationId)).toBe('u1');
	expect(getModels).not.toHaveBeenCalled();
});

test('a failed switch goes back to the previous org', async () => {
	organizations.set([personal, workspace]);
	activeOrganizationId.set('u1');
	getModels.mockRejectedValueOnce(new Error('offline'));

	await expect(switchOrganization('w1', 'token')).rejects.toThrow('offline');

	expect(get(activeOrganizationId)).toBe('u1');
	expect(get(models)).toEqual([{ id: 'model-of-u1' }]);
	expect(get(switchingOrganization)).toBe(false);
});
