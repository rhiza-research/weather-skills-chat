import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig, devices } from '@playwright/test';

const root = path.dirname(fileURLToPath(import.meta.url));
const baseURL = process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:3000';

export default defineConfig({
	testDir: './specs',
	fullyParallel: false,
	workers: 1,
	forbidOnly: !!process.env.CI,
	retries: process.env.CI ? 1 : 0,
	outputDir: './test-results',
	globalSetup: './global-setup.ts',
	reporter: process.env.CI
		? [
				['github'],
				['html', { outputFolder: './playwright-report', open: 'never' }],
				['junit', { outputFile: '../test-results/playwright.xml' }]
			]
		: [['list'], ['html', { outputFolder: './playwright-report', open: 'never' }]],
	use: {
		baseURL,
		trace: 'on-first-retry',
		screenshot: 'only-on-failure'
	},
	projects: [
		{
			name: 'chromium',
			testIgnore: /auth\.spec\.ts/,
			use: { ...devices['Desktop Chrome'], storageState: path.join(root, '.auth/admin.json') }
		},
		{
			name: 'chromium-signed-out',
			testMatch: /auth\.spec\.ts/,
			use: { ...devices['Desktop Chrome'], storageState: { cookies: [], origins: [] } }
		}
	]
});
