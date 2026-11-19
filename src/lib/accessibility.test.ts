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

const gray = Object.fromEntries(
	[
		...readFileSync('tailwind.config.js', 'utf8').matchAll(
			/(\d{2,3}): 'var\(--color-gray-\d+, (#[0-9a-f]{3,6})\)'/gi
		)
	].map((m) => [m[1], m[2]])
);
const css = readFileSync('src/app.css', 'utf8');
const role = (name: string) => {
	const apply = css.match(new RegExp(`\\.${name}\\s*\\{\\s*@apply ([^;]+);`))?.[1] ?? '';
	const light = apply.match(/(?<![:\w-])text-gray-(\d+)/)?.[1];
	const dark = apply.match(/(?<![\w-])dark:text-gray-(\d+)/)?.[1];
	return { light: gray[light as string], dark: gray[dark as string] };
};

// Surfaces text sits on: page, filled fields, tonal buttons.
const LIGHT = ['#ffffff', gray['50']];
const DARK = [gray['900'], gray['850']];

describe('colour contrast (WCAG 2.1 AA)', () => {
	it('reads the palette from tailwind.config.js', () => {
		expect(Object.keys(gray)).toContain('600');
	});

	for (const name of ['text-strong', 'text-body', 'text-muted', 'tab-idle']) {
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
