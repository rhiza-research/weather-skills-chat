import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { expect, test } from 'vitest';
import { htmlHasFigureJson, isFigureJson, shouldLoadArtifactList } from './artifactsList';

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

test('an HTML figure with a JSON sibling is opened from the JSON', () => {
	const files = [
		{ path: 'rain.html', kind: 'html' },
		{ path: 'rain.plotly.json', kind: 'file' },
		{ path: 'other.html', kind: 'html' }
	];
	expect(htmlHasFigureJson(files[0], files)).toBe(true);
	expect(htmlHasFigureJson({ path: 'rain.htm', kind: 'html' }, files)).toBe(true);
	expect(htmlHasFigureJson(files[2], files)).toBe(false);
	expect(htmlHasFigureJson(files[1], files)).toBe(false);
	expect(htmlHasFigureJson({ path: 'plot.png', kind: 'image' }, files)).toBe(false);
});

test('a figure JSON is hidden only beside its HTML artifact', () => {
	const files = [
		{ path: 'rain.html', kind: 'html' },
		{ path: 'rain.plotly.json', kind: 'file' },
		{ path: 'orphan.plotly.json', kind: 'file' }
	];
	expect(isFigureJson(files[1], files)).toBe(true);
	expect(isFigureJson(files[2], files)).toBe(false);
	expect(isFigureJson(files[0], files)).toBe(false);
	expect(isFigureJson({ path: 'other.plotly.json', kind: 'file' }, files)).toBe(false);
});
