import { expect, test } from '@playwright/test';
import { clearChats, seedChat } from '../../chats';
import { listing, openSidebar, waitForSocket } from '../../helpers';

test('reconnect refreshes the sidebar so chats created while offline appear', async ({
	page
}) => {
	await clearChats();
	const first = await seedChat('already listed', 'first reply');
	const socket = waitForSocket(page);
	await page.goto(`/c/${first.id}`);
	await socket;
	await openSidebar(page);
	await expect
		.poll(async () => (await listing(page)).chats.some((chat) => chat.id === first.id))
		.toBe(true);

	await page.context().setOffline(true);
	const created = await seedChat('created offline', 'offline reply');
	await page.context().setOffline(false);

	await expect
		.poll(async () => (await listing(page)).chats.some((chat) => chat.id === created.id), {
			timeout: 20_000
		})
		.toBe(true);
	await expect(page).toHaveURL(new RegExp(`/c/${first.id}`));
});
