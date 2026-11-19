import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const lum = (hex: string) => {
	let h = hex.replace('#', '');
	if (h.length === 3) h = [...h].map((c) => c + c).join('');
	const [r, g, b] = [0, 2, 4].map((i) => {
		const c = parseInt(h.slice(i, i + 2), 16) / 255;
		return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
	});
	return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
const contrast = (a: string, b: string) => {
	const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x);
	return (hi + 0.05) / (lo + 0.05);
};

const tw = readFileSync('src/tailwind.css', 'utf8');
const css = readFileSync('src/app.css', 'utf8');
const gray = Object.fromEntries(
	[...tw.matchAll(/--color-gray-(\d+): (#[0-9a-f]{3,6});/gi)].map((m) => [m[1], m[2]])
);
const block = (sel: string) => tw.match(new RegExp(`\\n\\t${sel} \\{([^}]*)\\}`))![1];
const token = (sel: string, name: string) => {
	const v = block(sel).match(new RegExp(`--${name}: var\\(--color-gray-(\\d+)\\)`))?.[1];
	return gray[v as string];
};
const role = (name: string) => ({ light: token(':root', name), dark: token('\\.dark', name) });

// Surfaces text sits on: page, filled fields, tonal buttons.
const LIGHT = ['#ffffff', token(':root', 'surface')]; // page, panel and surface
const DARK = [gray['900'], token('\\.dark', 'surface')];

describe('colour contrast (WCAG 2.1 AA)', () => {
	it('reads the palette from tailwind.css', () => {
		expect(Object.keys(gray)).toContain('600');
	});

	for (const name of ['strong', 'body', 'muted']) {
		it(`${name} text is at least 4.5:1 in light and dark`, () => {
			const { light, dark } = role(name);
			expect(light, `${name} light colour`).toBeTruthy();
			expect(dark, `${name} dark colour`).toBeTruthy();
			for (const bg of LIGHT) expect(contrast(light, bg)).toBeGreaterThanOrEqual(4.5);
			for (const bg of DARK) expect(contrast(dark, bg)).toBeGreaterThanOrEqual(4.5);
		});
	}

	it('the switch off-state outline is at least 3:1 against the page', () => {
		const sw = readFileSync('src/lib/components/common/Switch.svelte', 'utf8');
		const light = gray[sw.match(/(?<![:\w-])outline-gray-(\d+)/)![1]];
		const dark = gray[sw.match(/dark:outline-gray-(\d+)/)![1]];
		expect(contrast(light, '#ffffff')).toBeGreaterThanOrEqual(3);
		expect(contrast(dark, gray['900'])).toBeGreaterThanOrEqual(3);
	});

	it('the focus ring is at least 3:1 against the page', () => {
		const ring = (sel: string) =>
			css.match(new RegExp(`${sel}\\s*\\{\\s*--focus-ring:\\s*(#[0-9a-f]+)`, 'i'))![1];
		expect(contrast(ring(':root'), '#ffffff')).toBeGreaterThanOrEqual(3);
		expect(contrast(ring('\\.dark'), gray['900'])).toBeGreaterThanOrEqual(3);
	});
});
