import { expect, test, type Page } from '@playwright/test';
import { replaceAssistant, seedChat, sendTurn, sendTurnAtRevision } from '../../chats';

const ORIGINAL = 'cached reply before the other tab writes';

function watchChatGets(page: Page, id: string) {
	const hits: string[] = [];
	page.on('request', (request) => {
		if (request.method() !== 'GET') return;
		const path = new URL(request.url()).pathname;
		if (path === `/api/v1/chats/${id}`) hits.push(request.url());
	});
	return hits;
}

async function waitForSocket(page: Page) {
	await page.waitForEvent('websocket', {
		predicate: (socket) => socket.url().includes('socket.io'),
		timeout: 20_000
	});
}

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
	await expect.poll(() => hits.length - baseline, { timeout: 8_000 }).toBe(1);
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
	await page.waitForTimeout(500);
	await expect.poll(() => hits.length - baseline, { timeout: 4_000 }).toBe(0);
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

test('a stale expected_revision is a readable conflict, not a silent write', async () => {
	const { id, token } = await seedChat('revision conflict', ORIGINAL);
	const result = await sendTurnAtRevision(token, id, 'should not land', 0);
	expect(result.status).toBe(409);
	expect(result.body.toLowerCase()).toContain('another user');
	expect(result.body).not.toMatch(/\b409\b/);
});
