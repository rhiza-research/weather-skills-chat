import { expect, test } from '@playwright/test';
import { seedChat, uploadArtifact } from '../../chats';
import { waitForSocket } from '../../helpers';

test('a failed first artifacts fetch is retried the next time the panel opens', async ({
	page
}) => {
	const { id, token } = await seedChat('artifacts retry', 'reply');
	await uploadArtifact(token, id, 'plot.png', Buffer.from('png'), 'image/png');

	let failed = false;
	const okGets: number[] = [];
	await page.route(`**/api/v1/chats/${id}/artifacts**`, async (route) => {
		if (route.request().method() === 'GET') {
			if (!failed) {
				failed = true;
				await route.fulfill({ status: 502, body: 'blip' });
				return;
			}
			okGets.push(Date.now());
		}
		await route.continue();
	});

	const socket = waitForSocket(page);
	await page.goto(`/c/${id}`);
	await socket;
	const toggle = page.locator('#artifacts-toggle-button');
	await expect(toggle).toBeVisible();
	await toggle.click();
	await page.waitForTimeout(400);
	await toggle.click();
	await toggle.click();
	await expect.poll(() => okGets.length, { timeout: 15_000 }).toBeGreaterThan(0);
});
