import { expect, test } from '@playwright/test';
import { seedChat, uploadArtifact } from '../../chats';
import { waitForSocket } from '../../helpers';

test('a failed first artifacts fetch is retried the next time the panel opens', async ({
	page
}) => {
	const { id, token } = await seedChat('artifacts retry', 'reply');
	await uploadArtifact(token, id, 'plot.png', Buffer.from('png'), 'image/png');

	let failed = false;
	await page.route(`**/api/v1/chats/${id}/artifacts**`, async (route) => {
		if (!failed && route.request().method() === 'GET') {
			failed = true;
			await route.fulfill({ status: 502, body: 'blip' });
			return;
		}
		await route.continue();
	});

	const socket = waitForSocket(page);
	await page.goto(`/c/${id}`);
	await socket;
	await page.locator('#artifacts-toggle-button').click();
	await page.waitForTimeout(500);
	await page.locator('#artifacts-toggle-button').click();
	await page.waitForTimeout(200);
	await page.locator('#artifacts-toggle-button').click();
	await expect(page.getByText('plot.png')).toBeVisible({ timeout: 10_000 });
});
