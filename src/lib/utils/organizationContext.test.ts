import { expect, test } from 'vitest';
import { get } from 'svelte/store';
import { activeOrganizationId, organizations } from '$lib/stores';
import { openInvitedOrganization, platformAdminMembership } from './organizationContext';

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
