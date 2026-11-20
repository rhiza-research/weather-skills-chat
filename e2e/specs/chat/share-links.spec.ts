import { expect, test } from '@playwright/test';
import { clearChats, seedChat } from '../../chats';
import { waitForSocket } from '../../helpers';

test('Share links stack up, with a greyed spinning row while one is made', async ({
	page,
	context
}) => {
	await context.grantPermissions(['clipboard-read', 'clipboard-write']);
	await page.goto('/');
	await clearChats();
	const chat = await seedChat('shared chat', 'shared reply');

	let releaseShare = () => {};
	const shareHeld = new Promise<void>((resolve) => (releaseShare = resolve));
	await page.route(`**/api/v1/chats/${chat.id}/share`, async (route) => {
		await shareHeld;
		await route.continue();
	});

	const socket = waitForSocket(page);
	await page.goto(`/c/${chat.id}`);
	await socket;

	const openModal = async () => {
		await page.locator('#chat-context-menu-button').click();
		await page.locator('#chat-share-button').click();
	};
	await openModal();
	const create = page.getByRole('button', { name: 'Create share link' });
	const rows = page.getByRole('listitem').filter({ hasText: 'Created' });
	await expect(rows).toHaveCount(0);

	await create.click();
	const pendingRow = rows.and(page.locator('[aria-busy="true"]'));
	await expect(pendingRow).toHaveCount(1);
	await expect(pendingRow).toHaveClass(/opacity-50/);
	await expect(pendingRow.locator('svg')).toBeVisible();
	await expect(create).toBeDisabled();

	releaseShare();
	await expect(pendingRow).toHaveCount(0);
	await expect(rows).toHaveCount(1);

	// A second link adds a row instead of replacing the first.
	await page.unroute(`**/api/v1/chats/${chat.id}/share`);
	await create.click();
	await expect(rows).toHaveCount(2);
	await expect(rows.first()).toContainText('Expires');

	// Each row copies its own link.
	await rows.nth(1).getByRole('button', { name: 'Copy link' }).click();
	const copied = await page.evaluate(() => navigator.clipboard.readText());
	expect(copied).toMatch(new RegExp(`/s/[0-9a-f-]{36}$`));

	// Reopening lists the same links.
	await page.keyboard.press('Escape');
	await openModal();
	await expect(rows).toHaveCount(2);
});
