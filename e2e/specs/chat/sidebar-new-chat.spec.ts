import { expect, test, type Route } from '@playwright/test';
import { seedChat } from '../../chats';
import { openSidebar } from '../../helpers';

const REPLY = 'reply that stays after a quick return';

test('a chat link clicked before New Chat finishes keeps the chat open', async ({ page }) => {
	const { id } = await seedChat('quick return', REPLY);
	await page.goto(`/c/${id}`);
	await expect(page.getByText(REPLY)).toBeVisible();
	await openSidebar(page);

	// Every route module the chat page uses is loaded by now, so the next one requested belongs
	// to "/". Holding it keeps goto('/') from finishing until the chat link has navigated.
	let release = () => {};
	const held = new Promise<void>((resolve) => {
		release = resolve;
	});
	const heldUrls: string[] = [];
	const hold = async (route: Route) => {
		heldUrls.push(route.request().url());
		await held;
		await route.continue();
	};
	await page.route('**/_app/immutable/nodes/*.js', hold);

	try {
		await page.locator('#sidebar-new-chat-button').click();
		await expect.poll(() => heldUrls.length).toBeGreaterThan(0);
		await page.locator(`#sidebar a[href="/c/${id}"]`).click();
		await expect(page).toHaveURL(new RegExp(`/c/${id}$`));

		const loaded = heldUrls.map((url) => page.waitForResponse(url));
		release();
		await Promise.all(loaded);
		// goto('/') settles in microtasks once its module loads, and the New Chat handler then
		// queues its button click with setTimeout(0). A timer queued after that runs after it.
		await page.evaluate(() => new Promise((resolve) => setTimeout(resolve, 0)));
	} finally {
		release();
		await page.unroute('**/_app/immutable/nodes/*.js', hold);
	}

	await expect(page).toHaveURL(new RegExp(`/c/${id}$`));
	await expect(page.getByText(REPLY)).toBeVisible();
});
