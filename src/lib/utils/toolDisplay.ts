/** Label bits and selection helpers for tools/skills. */

type ToolLike = {
	id?: string;
	name?: string;
	meta?: {
		description?: string;
		manifest?: {
			kind?: string;
			version?: string | number | null;
			git_ref?: string | null;
			git_url?: string | null;
			skill_name?: string | null;
			enabled?: boolean | null;
		};
	};
};

export type ToolWithId = ToolLike & { id: string };

export const isSkillTool = (tool: ToolLike | null | undefined): boolean =>
	tool?.meta?.manifest?.kind === 'skill';

/** Global default from Workspace; missing/undefined means enabled. */
export const isSkillDefaultEnabled = (tool: ToolLike | null | undefined): boolean => {
	if (!isSkillTool(tool)) {
		return true;
	}
	return tool?.meta?.manifest?.enabled !== false;
};

export const toolSkillVersion = (tool: ToolLike | null | undefined): string => {
	const version = tool?.meta?.manifest?.version;
	if (version === null || version === undefined || version === '') {
		return '';
	}
	return String(version);
};

export const toolSkillGitRef = (tool: ToolLike | null | undefined): string => {
	const ref = tool?.meta?.manifest?.git_ref;
	if (!ref || typeof ref !== 'string') {
		return '';
	}
	return ref.trim();
};

/** Parse `org/repo` from a git remote URL when possible. */
export const parseGitOrgRepo = (gitUrl: string | null | undefined): string => {
	if (!gitUrl || typeof gitUrl !== 'string') {
		return '';
	}
	let raw = gitUrl.trim();
	if (!raw) {
		return '';
	}

	// git@host:org/repo(.git)
	const scp = raw.match(/^git@[^:]+:(.+)$/i);
	if (scp) {
		raw = scp[1];
	} else {
		try {
			const withScheme = /^[a-z][a-z0-9+.-]*:/i.test(raw) ? raw : `https://${raw}`;
			const url = new URL(withScheme);
			raw = url.pathname;
		} catch {
			// keep raw
		}
	}

	raw = raw.replace(/^\/+/, '').replace(/\.git$/i, '');
	const parts = raw.split('/').filter(Boolean);
	if (parts.length >= 2) {
		return `${parts[parts.length - 2]}/${parts[parts.length - 1]}`;
	}
	return parts[0] || '';
};

/**
 * `org/repo@branch` for skill provenance. Falls back to `@branch` or org/repo alone.
 */
export const toolSkillRepoRef = (tool: ToolLike | null | undefined): string => {
	const orgRepo = parseGitOrgRepo(tool?.meta?.manifest?.git_url);
	const ref = toolSkillGitRef(tool);
	if (orgRepo && ref) {
		return `${orgRepo}@${ref}`;
	}
	if (orgRepo) {
		return orgRepo;
	}
	if (ref) {
		return `@${ref}`;
	}
	return '';
};

/**
 * Display name for selectors. Prefer skill_name when present so we don't
 * double-append version if tool.name is already "name@version".
 */
export const toolBaseName = (tool: ToolLike | null | undefined): string => {
	const skillName = tool?.meta?.manifest?.skill_name;
	if (typeof skillName === 'string' && skillName.trim()) {
		return skillName.trim();
	}
	return (tool?.name ?? '').trim() || 'tool';
};

/** Compact one-line label: name · v1.2.3 · org/repo@branch */
export const toolSelectionLabel = (tool: ToolLike | null | undefined): string => {
	const base = toolBaseName(tool);
	if (!isSkillTool(tool)) {
		return tool?.name?.trim() || base;
	}
	const version = toolSkillVersion(tool);
	const repoRef = toolSkillRepoRef(tool);
	const parts = [base];
	if (version) {
		parts.push(`v${version}`);
	}
	if (repoRef) {
		parts.push(repoRef);
	}
	return parts.join(' ');
};

/** Stable identity for skill duplicates across packs/refs. */
export const skillDedupeKey = (tool: ToolLike | null | undefined): string | null => {
	if (!isSkillTool(tool)) {
		return null;
	}
	const name = tool?.meta?.manifest?.skill_name ?? toolBaseName(tool);
	const key = typeof name === 'string' ? name.trim().toLowerCase() : '';
	return key || null;
};

/** Numeric-aware version compare; empty versions sort lowest. */
export const compareSkillVersions = (a: string, b: string): number => {
	const left = (a || '0').replace(/^v/i, '');
	const right = (b || '0').replace(/^v/i, '');
	return left.localeCompare(right, undefined, { numeric: true, sensitivity: 'base' });
};

const isStrictlyHigherSkillVersion = (candidate: ToolLike, current: ToolLike): boolean =>
	compareSkillVersions(toolSkillVersion(candidate), toolSkillVersion(current)) > 0;

/**
 * Collapse duplicate skills (same skill_name) to the highest version.
 * Non-skill tools are kept as-is. Preserves first-seen order.
 */
export const dedupeToolsForSelection = <T extends ToolWithId>(tools: T[]): T[] => {
	const result: T[] = [];
	const indexByKey = new Map<string, number>();

	for (const tool of tools) {
		const key = skillDedupeKey(tool);
		if (key === null) {
			result.push(tool);
			continue;
		}

		const existingIndex = indexByKey.get(key);
		if (existingIndex === undefined) {
			indexByKey.set(key, result.length);
			result.push(tool);
			continue;
		}

		if (isStrictlyHigherSkillVersion(tool, result[existingIndex])) {
			result[existingIndex] = tool;
		}
	}

	return result;
};

/**
 * Map selected tool ids onto the highest-version skill when a lower
 * duplicate was previously selected.
 */
export const remapSelectedToolIdsToHighestSkills = (
	selectedToolIds: string[],
	allTools: ToolWithId[]
): string[] => {
	const winnerByKey = new Map<string, string>();
	for (const tool of dedupeToolsForSelection(allTools)) {
		const key = skillDedupeKey(tool);
		if (key) {
			winnerByKey.set(key, tool.id);
		}
	}

	const idToKey = new Map<string, string | null>();
	for (const tool of allTools) {
		idToKey.set(tool.id, skillDedupeKey(tool));
	}

	const out: string[] = [];
	const seen = new Set<string>();
	for (const id of selectedToolIds) {
		const key = idToKey.get(id);
		const mapped = key ? (winnerByKey.get(key) ?? id) : id;
		if (!seen.has(mapped)) {
			seen.add(mapped);
			out.push(mapped);
		}
	}
	return out;
};

/** IDs to enable by default in chat (deduped skills; respects pack toggles). */
export const defaultEnabledToolIds = (allTools: ToolWithId[]): string[] => {
	const eligible = allTools.filter(isSkillDefaultEnabled);
	// Dedupe only among enabled skills so a disabled higher version cannot win.
	return dedupeToolsForSelection(eligible).map((t) => t.id);
};
