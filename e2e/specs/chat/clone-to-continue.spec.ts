import { expect, test } from '@playwright/test';
import { clearChats, seedChat } from '../../chats';
import { waitForSocket } from '../../helpers';

test('Clone to continue shows a spinner while cloning, then opens the clone', async ({ page }) => {
	await page.goto('/');
	await clearChats();
	const source = await seedChat('teammate chat', 'teammate reply');

	// The suite has one account, so show its own chat as a teammate's to get the read-only banner.
	await page.route(`**/api/v1/chats/${source.id}`, async (route) => {
		if (route.request().method() !== 'GET') return route.fallback();
		const response = await route.fetch();
		await route.fulfill({
			response,
			json: { ...(await response.json()), user_id: 'e2e-teammate' }
		});
	});
	let releaseClone = () => {};
	const cloneHeld = new Promise<void>((resolve) => (releaseClone = resolve));
	await page.route(`**/api/v1/chats/${source.id}/clone`, async (route) => {
		await cloneHeld;
		await route.continue();
	});

	const socket = waitForSocket(page);
	await page.goto(`/c/${source.id}`);
	await socket;

	const clone = page.getByRole('button', { name: 'Clone to continue' });
	await clone.click();
	await expect(clone).toBeDisabled();
	await expect(clone.locator('svg')).toBeVisible();

	releaseClone();
	await page.waitForURL(
		(url) => url.pathname.startsWith('/c/') && url.pathname !== `/c/${source.id}`
	);
	await expect(page.getByText('teammate reply')).toBeVisible();
	await expect(clone).toHaveCount(0);
	await expect(page.locator('#chat-input')).toBeVisible();
});
