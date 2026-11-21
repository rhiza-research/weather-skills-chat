import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { expect, test } from 'vitest';

const here = dirname(fileURLToPath(import.meta.url));

// Chat text is written by users and models, so markdown HTML may reach the page
// only as `html`, the DOMPurify output. A raw `{@html token.text}` lets a shared
// chat run script for whoever opens it.
test.each(['MarkdownTokens.svelte', 'MarkdownInlineTokens.svelte'])(
	'%s inserts only sanitized HTML',
	(file) => {
		const source = readFileSync(resolve(here, file), 'utf8');
		const inserted = [...source.matchAll(/\{@html\s+([^}]+)\}/g)].map((m) => m[1].trim());
		expect(inserted.length).toBeGreaterThan(0);
		expect(inserted.every((expr) => expr === 'html')).toBe(true);
		expect(source).toContain('const html = DOMPurify.sanitize(token.text)');
	}
);

// SVG artifacts and mermaid diagrams come from chat text too.
test('SVGPanZoom sanitizes the SVG it inserts', () => {
	const source = readFileSync(resolve(here, '../../../common/SVGPanZoom.svelte'), 'utf8');
	const inserted = source
		.split('\n')
		.filter((line) => line.includes('{@html'))
		.map((line) => line.trim());
	expect(inserted).toEqual([
		'{@html DOMPurify.sanitize(svg, { USE_PROFILES: { svg: true, svgFilters: true } })}'
	]);
});

test('mermaid renders in strict mode', () => {
	const source = readFileSync(resolve(here, '../CodeBlock.svelte'), 'utf8');
	expect(source).toContain("securityLevel: 'strict'");
	expect(source).not.toContain("securityLevel: 'loose'");
});
