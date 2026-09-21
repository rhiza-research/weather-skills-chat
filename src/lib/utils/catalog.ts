export const PLATFORM_ORG_ID = 'platform';

export const isPublicItem = (item: { visibility?: string } | null | undefined) =>
	item?.visibility === 'public';

export const isCatalogEnabled = (item: { enabled?: boolean } | null | undefined) =>
	item?.enabled !== false;

export const isOrgAdminRole = (org: { role?: string } | null | undefined) =>
	org?.role === 'owner' || org?.role === 'admin';

export const canAddKind = (
	org:
		| {
				can_add_models?: boolean;
				can_add_skills?: boolean;
				can_add_knowledge?: boolean;
		  }
		| null
		| undefined,
	kind: 'models' | 'skills' | 'knowledge'
) => {
	if (!org) return false;
	if (kind === 'models') return !!org.can_add_models;
	if (kind === 'skills') return !!org.can_add_skills;
	return !!org.can_add_knowledge;
};

export const canManageCatalogItem = (
	catalog: 'public' | 'org',
	item: { visibility?: string } | null | undefined,
	org: { role?: string } | null | undefined
) => {
	if (isPublicItem(item)) return catalog === 'public';
	return isOrgAdminRole(org);
};
