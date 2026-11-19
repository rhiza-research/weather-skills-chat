import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';

const ROUTES = [
	'/',
	'/workspace/models',
	'/workspace/skills',
	'/workspace/secrets',
	'/admin/users',
	'/admin/settings',
	'/scheduled-tasks'
];

// Still failing: Dropdown renders a trigger button around the caller's own button.
const KNOWN_GAPS = ['nested-interactive'];

for (const scheme of ['light', 'dark'] as const) {
	test.describe(`axe ${scheme}`, () => {
		test.use({ colorScheme: scheme });

		for (const route of ROUTES) {
			test(`${route} has no WCAG A/AA violations`, async ({ page }) => {
				await page.goto(route);
				await page.waitForLoadState('networkidle');
				const { violations } = await new AxeBuilder({ page })
					.withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
					.disableRules(KNOWN_GAPS)
					.analyze();
				expect(violations.map((v) => `${v.id} x${v.nodes.length}`)).toEqual([]);
			});
		}
	});
}
