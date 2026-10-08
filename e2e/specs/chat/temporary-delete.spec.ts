import { expect, test } from '@playwright/test';
import { waitForSocket } from '../../helpers';

test('deleting a message in a temporary chat does not POST history', async ({ page }) => {
	const historyPosts: string[] = [];
	page.on('request', (request) => {
		if (request.method() !== 'POST') return;
		if (new URL(request.url()).pathname.includes('/history')) {
			historyPosts.push(request.url());
		}
	});
	await page.route('**/api/chat/completions', async (route) => {
		await route.fulfill({
			status: 400,
			contentType: 'application/json',
			body: JSON.stringify({ detail: 'nope' })
		});
	});
	const socket = waitForSocket(page);
	await page.goto('/?temporary-chat=true');
	await socket;
	await expect(page.locator('#chat-input')).toBeVisible();
	const input = page.locator('#chat-input');
	await input.fill('throwaway prompt');
	await input.press('Enter');
	const userLine = page.getByText('throwaway prompt').first();
	await expect(userLine).toBeVisible({ timeout: 10_000 });
	await userLine.hover();
	const del = page.getByRole('button', { name: /^delete$/i }).first();
	await expect(del).toBeVisible({ timeout: 10_000 });
	await del.click();
	const confirm = page.getByRole('button', { name: /^confirm$/i });
	if (await confirm.isVisible().catch(() => false)) await confirm.click();
	await expect(page.getByText('throwaway prompt')).toHaveCount(0, { timeout: 10_000 });
	expect(historyPosts).toEqual([]);
});
