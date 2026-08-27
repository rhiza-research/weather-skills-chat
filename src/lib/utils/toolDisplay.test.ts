import { describe, expect, it } from 'vitest';
import {
	compareSkillVersions,
	defaultEnabledToolIds,
	dedupeToolsForSelection,
	isSkillDefaultEnabled,
	parseGitOrgRepo,
	remapSelectedToolIdsToHighestSkills,
	toolSelectionLabel,
	toolSkillRepoRef
} from './toolDisplay';

const skill = (
	id: string,
	skillName: string,
	version: string,
	gitRef = 'main',
	gitUrl = 'https://github.com/rhiza-research/forecasting-skills.git',
	enabled: boolean | undefined = undefined
) => ({
	id,
	name: `${skillName}@${version}`,
	meta: {
		manifest: {
			kind: 'skill' as const,
			skill_name: skillName,
			version,
			git_ref: gitRef,
			git_url: gitUrl,
			...(enabled === undefined ? {} : { enabled })
		}
	}
});

describe('parseGitOrgRepo', () => {
	it('parses https and ssh remotes', () => {
		expect(parseGitOrgRepo('https://github.com/org/repo.git')).toBe('org/repo');
		expect(parseGitOrgRepo('git@github.com:org/repo.git')).toBe('org/repo');
		expect(parseGitOrgRepo('https://github.com/org/repo')).toBe('org/repo');
	});
});

describe('toolSkillRepoRef', () => {
	it('formats org/repo@branch', () => {
		expect(toolSkillRepoRef(skill('a', 'plot', '1.0.0', 'develop'))).toBe(
			'rhiza-research/forecasting-skills@develop'
		);
	});
});

describe('compareSkillVersions', () => {
	it('orders semver-like strings numerically', () => {
		expect(compareSkillVersions('1.10.0', '1.9.0')).toBeGreaterThan(0);
		expect(compareSkillVersions('2.0', '1.9.9')).toBeGreaterThan(0);
		expect(compareSkillVersions('1.0.0', '1.0.0')).toBe(0);
	});

	it('treats empty as lowest', () => {
		expect(compareSkillVersions('', '0.1.0')).toBeLessThan(0);
	});
});

describe('dedupeToolsForSelection', () => {
	it('keeps only the highest version per skill_name', () => {
		const tools = [
			skill('a', 'plot', '1.0.0', 'main'),
			skill('b', 'plot', '1.2.0', 'develop'),
			skill('c', 'clip-region', '0.3.0'),
			{ id: 'custom', name: 'Custom Tool', meta: {} }
		];

		const result = dedupeToolsForSelection(tools);
		expect(result.map((t) => t.id)).toEqual(['b', 'c', 'custom']);
	});

	it('keeps the first entry when versions are equal', () => {
		const tools = [skill('a', 'plot', '1.0.0', 'main'), skill('b', 'plot', '1.0.0', 'old')];
		expect(dedupeToolsForSelection(tools).map((t) => t.id)).toEqual(['a']);
	});
});

describe('remapSelectedToolIdsToHighestSkills', () => {
	it('rewrites a lower-version selection to the winner', () => {
		const tools = [skill('old', 'plot', '1.0.0'), skill('new', 'plot', '2.0.0')];
		expect(remapSelectedToolIdsToHighestSkills(['old'], tools)).toEqual(['new']);
	});

	it('dedupes multiple selected versions of the same skill', () => {
		const tools = [skill('old', 'plot', '1.0.0'), skill('new', 'plot', '2.0.0')];
		expect(remapSelectedToolIdsToHighestSkills(['old', 'new'], tools)).toEqual(['new']);
	});
});

describe('toolSelectionLabel', () => {
	it('includes version and org/repo@branch for skills', () => {
		expect(toolSelectionLabel(skill('a', 'plot', '1.2.0', 'main'))).toBe(
			'plot v1.2.0 rhiza-research/forecasting-skills@main'
		);
	});
});

describe('defaultEnabledToolIds', () => {
	it('treats missing enabled as on', () => {
		expect(isSkillDefaultEnabled(skill('a', 'plot', '1.0.0'))).toBe(true);
	});

	it('excludes globally disabled skills from defaults', () => {
		const tools = [
			skill('on', 'plot', '2.0.0', 'main', undefined, true),
			skill('off', 'fetch', '1.0.0', 'main', undefined, false),
			{ id: 'custom', name: 'Custom Tool' }
		];
		expect(defaultEnabledToolIds(tools as any).sort()).toEqual(['custom', 'on']);
	});

	it('still prefers highest version among enabled skills', () => {
		const tools = [
			skill('old', 'plot', '1.0.0', 'main', undefined, true),
			skill('new', 'plot', '2.0.0', 'main', undefined, true),
			skill('disabled-higher', 'plot', '3.0.0', 'main', undefined, false)
		];
		// disabled 3.0 is excluded from eligible; remap among remaining still picks 2.0
		expect(defaultEnabledToolIds(tools)).toEqual(['new']);
	});
});
