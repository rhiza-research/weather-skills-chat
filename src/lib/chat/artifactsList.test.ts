import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { expect, test } from 'vitest';
import { shouldLoadArtifactList } from './artifactsList';

const artifactsSource = readFileSync(
	resolve(dirname(fileURLToPath(import.meta.url)), '../components/chat/Artifacts.svelte'),
	'utf8'
);

test('a successful list, including empty, does not refetch', () => {
	expect(shouldLoadArtifactList([])).toBe(false);
	expect(shouldLoadArtifactList([{ name: 'plot.png' }])).toBe(false);
});

test('a missing or failed list can be fetched again', () => {
	expect(shouldLoadArtifactList(undefined)).toBe(true);
	expect(shouldLoadArtifactList(null)).toBe(true);
});

test('the artifacts panel uses shouldLoadArtifactList instead of a sticky false key', () => {
	expect(artifactsSource).toMatch(/shouldLoadArtifactList/);
	expect(artifactsSource).not.toMatch(/\$\{.*\}:\$\{hasList\}/);
});
