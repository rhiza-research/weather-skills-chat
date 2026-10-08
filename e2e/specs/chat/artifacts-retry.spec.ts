import { expect, test } from '@playwright/test';
import { seedChat, uploadArtifact } from '../../chats';
import { waitForSocket } from '../../helpers';

test('a failed first artifacts fetch is retried the next time the panel opens', async ({
	page
}) => {
	const { id, token } = await seedChat('artifacts retry', 'reply');
	await uploadArtifact(token, id, 'plot.png', Buffer.from('png'), 'image/png');

	const socket = waitForSocket(page);
	await page.goto(`/c/${id}`);
	await socket;
	const toggle = page.locator('#artifacts-toggle-button');
	await expect(toggle).toBeVisible();

	// Fail only the first listing after the panel is about to open, so a
	// successful preload does not consume the 502.
	let failed = false;
	await page.route(`**/api/v1/chats/${id}/artifacts**`, async (route) => {
		if (!failed && route.request().method() === 'GET') {
			failed = true;
			await route.fulfill({ status: 502, body: 'blip' });
			return;
		}
		await route.continue();
	});

	await toggle.click();
	await expect(page.getByText(/no files in this chat yet|plot\.png/i)).toBeVisible({
		timeout: 10_000
	});
	await toggle.click();
	await toggle.click();
	await expect(page.getByText('plot.png')).toBeVisible({ timeout: 15_000 });
});
