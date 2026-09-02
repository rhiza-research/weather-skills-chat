type AccessControl = {
	read?: { user_ids?: string[]; group_ids?: string[]; team_ids?: string[] };
	write?: { user_ids?: string[]; group_ids?: string[]; team_ids?: string[] };
} | null;

type UserLike = {
	id?: string;
	role?: string;
	permissions?: {
		sharing?: Record<string, boolean>;
	};
};

export function isPrivateAccess(accessControl: AccessControl): boolean {
	return accessControl !== null && Object.keys(accessControl).length === 0;
}

export function isPublicAccess(accessControl: AccessControl): boolean {
	return accessControl === null;
}

function hasExplicitGrants(accessControl: AccessControl): boolean {
	if (!accessControl) return false;
	for (const section of [accessControl.read, accessControl.write]) {
		if (
			(section?.user_ids?.length ?? 0) > 0 ||
			(section?.group_ids?.length ?? 0) > 0 ||
			(section?.team_ids?.length ?? 0) > 0
		) {
			return true;
		}
	}
	return false;
}

function hasAclGrant(
	userId: string,
	permission: 'read' | 'write',
	accessControl: AccessControl,
	groupIds: string[] = []
): boolean {
	if (isPublicAccess(accessControl)) {
		return permission === 'read';
	}
	if (!accessControl) return false;

	const section = accessControl[permission] ?? {};
	const userIds = section.user_ids ?? [];
	const groupIdsInAcl = section.group_ids ?? [];

	return (
		userIds.includes(userId) ||
		groupIdsInAcl.some((gid) => groupIds.includes(gid))
	);
}

/** Mirrors backend user_owns_or_has_access for workspace UI affordances. */
export function userCanAccessResource(
	user: UserLike | null | undefined,
	ownerUserId: string | null | undefined,
	accessControl: AccessControl,
	permission: 'read' | 'write' = 'read',
	groupIds: string[] = []
): boolean {
	if (!user?.id) return false;
	if (ownerUserId && ownerUserId === user.id) return true;

	if (user.role === 'admin') {
		if (isPrivateAccess(accessControl)) return false;
		if (permission === 'read') {
			return isPublicAccess(accessControl) || hasAclGrant(user.id, 'read', accessControl, groupIds);
		}
		return isPublicAccess(accessControl) || hasAclGrant(user.id, 'write', accessControl, groupIds);
	}

	if (isPublicAccess(accessControl)) {
		return permission === 'read';
	}

	return hasAclGrant(user.id, permission, accessControl, groupIds);
}

export function userCanSetSharingAccess(
	user: UserLike | null | undefined,
	ownerUserId: string | null | undefined,
	accessControl: AccessControl,
	sharingPermissionKey: string,
	groupIds: string[] = []
): boolean {
	if (!user?.id) return false;
	// Owners use the sharing permission; do not gate on current ACL shape
	// (private `{}` expands in the form and would otherwise flip this).
	if (user.id === ownerUserId) {
		if (user.role === 'admin') return true;
		return Boolean(user.permissions?.sharing?.[sharingPermissionKey]);
	}
	if (user.role === 'admin') {
		return userCanAccessResource(user, ownerUserId, accessControl, 'write', groupIds);
	}
	return false;
}
