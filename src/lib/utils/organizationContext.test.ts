import { expect, test } from 'vitest';
import { platformAdminMembership } from './organizationContext';

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
