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
			status: 200,
			contentType: 'text/event-stream',
			body: 'data: {"choices":[{"delta":{"content":"temp reply"}}]}\n\ndata: [DONE]\n\n'
		});
	});
	const socket = waitForSocket(page);
	await page.goto('/?temporary-chat=true');
	await socket;
	await expect(page.locator('#chat-input')).toBeVisible();
	await page.locator('#chat-input').fill('throwaway prompt');
	await page.locator('#chat-input').press('Enter');
	const userLine = page.getByText('throwaway prompt');
	await expect(userLine.first()).toBeVisible({ timeout: 10_000 });
	await userLine.first().hover();
	const del = page.getByRole('button', { name: /delete/i }).first();
	await expect(del).toBeVisible();
	await del.click();
	const confirm = page.getByRole('button', { name: /delete/i }).last();
	if (await confirm.isVisible().catch(() => false)) await confirm.click();
	await page.waitForTimeout(500);
	expect(historyPosts).toEqual([]);
	await expect(page.locator('body')).not.toContainText(/not found|failed to save|error/i);
});
