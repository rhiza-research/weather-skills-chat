import { expect, test } from '@playwright/test';
import { replaceAssistant, seedChat, sendTurn } from '../../chats';
import { waitForSocket, watchChatGets } from '../../helpers';

const ORIGINAL = 'cached reply before the other tab writes';

test('a cached unopened chat is fetched once when another tab updates it', async ({ page }) => {
	const { id, token } = await seedChat('unopened cache', ORIGINAL);
	const hits = watchChatGets(page, id);
	const socket = waitForSocket(page);

	await page.goto('/');
	await socket;
	await expect.poll(() => hits.length, { timeout: 20_000 }).toBeGreaterThan(0);
	await page.waitForTimeout(1000);
	const baseline = hits.length;
	expect(page.url()).not.toContain(`/c/${id}`);

	await replaceAssistant(token, id, `${ORIGINAL}\n\nupdated while closed`);
	await page.waitForTimeout(2000);

	expect(hits.length - baseline).toBe(1);
});

test('an opened chat that is no longer on screen is not fetched when another tab updates it', async ({
	page
}) => {
	const { id, token } = await seedChat('hidden open chat', ORIGINAL);
	const hits = watchChatGets(page, id);
	const socket = waitForSocket(page);

	await page.goto(`/c/${id}`);
	await socket;
	await expect(page.getByText(ORIGINAL)).toBeVisible();
	await expect.poll(() => hits.length, { timeout: 20_000 }).toBeGreaterThan(0);
	await page.locator('#sidebar-toggle-button').click();
	await page.locator('#sidebar-new-chat-button').click();
	await expect(page).not.toHaveURL(new RegExp(`/c/${id}$`));
	await page.waitForTimeout(500);
	const baseline = hits.length;

	await replaceAssistant(token, id, `${ORIGINAL}\n\nupdated while hidden`);
	await page.waitForTimeout(2000);

	expect(hits.length - baseline).toBe(0);
});

test('the other open tab shows a message this tab sends', async ({ page }) => {
	const sent = 'SENT-from-this-tab';
	const { id, token } = await seedChat('two open tabs', ORIGINAL);
	const other = await page.context().newPage();
	const hits = watchChatGets(other, id);
	const sentFrom = waitForSocket(page);
	const listening = waitForSocket(other);

	await page.goto(`/c/${id}`);
	await other.goto(`/c/${id}`);
	await sentFrom;
	await listening;
	await expect(page.getByText(ORIGINAL)).toBeVisible();
	await expect(other.getByText(ORIGINAL)).toBeVisible();
	await expect.poll(() => hits.length, { timeout: 20_000 }).toBeGreaterThan(0);
	const baseline = hits.length;

	await sendTurn(token, id, sent);

	await expect(other.getByText(sent)).toBeVisible({ timeout: 8_000 });
	expect(hits.length - baseline).toBe(0);
});
