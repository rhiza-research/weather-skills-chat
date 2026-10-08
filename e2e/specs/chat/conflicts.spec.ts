import { expect, test } from '@playwright/test';
import { getChat, patchHistory, seedChat } from '../../chats';
import { waitForSocket } from '../../helpers';

const conflictBody = (revision: number) =>
	JSON.stringify({
		detail: {
			message: 'Another user has edited the chat. Please try again.',
			revision
		}
	});

async function sendComposer(page: { locator: (sel: string) => any }, text: string) {
	const input = page.locator('#chat-input');
	await expect(input).toBeVisible();
	await input.fill(text);
	await page.locator('#send-message-button').click();
}

test('a stale send retries after refetch and does not show a raw 409', async ({ page }) => {
	const { id } = await seedChat('conflict send', 'original reply');
	const socket = waitForSocket(page);
	let first = true;
	const completions: number[] = [];
	await page.route('**/api/chat/completions', async (route) => {
		completions.push(first ? 409 : 200);
		if (first) {
			first = false;
			await route.fulfill({
				status: 409,
				contentType: 'application/json',
				body: conflictBody(1)
			});
			return;
		}
		await route.continue();
	});
	await page.goto(`/c/${id}`);
	await socket;
	await expect(page.getByText('original reply')).toBeVisible();
	await sendComposer(page, 'follow up after a conflict');
	await expect.poll(() => completions.length, { timeout: 15_000 }).toBeGreaterThan(1);
	await expect(page.locator('body')).not.toContainText(/\b409\b/);
});

test('a send that stays in conflict shows the chat-edited message', async ({ page }) => {
	const { id } = await seedChat('conflict sticky', 'original reply');
	const socket = waitForSocket(page);
	const completions: number[] = [];
	await page.route('**/api/chat/completions', async (route) => {
		completions.push(409);
		await route.fulfill({
			status: 409,
			contentType: 'application/json',
			body: conflictBody(1)
		});
	});
	await page.goto(`/c/${id}`);
	await socket;
	await expect(page.getByText('original reply')).toBeVisible();
	await sendComposer(page, 'this should stay conflicted');
	await expect.poll(() => completions.length, { timeout: 15_000 }).toBeGreaterThan(1);
	await expect(
		page.locator('[data-sonner-toast]').getByText(/another user has edited the chat/i)
	).toBeVisible({ timeout: 10_000 });
	await expect(page.locator('body')).not.toContainText(/\b409\b/);
});

test('an edit that hits 409 is reapplied after the refetch', async ({ page }) => {
	const { id, token } = await seedChat('conflict edit', 'original reply');
	const socket = waitForSocket(page);
	await page.goto(`/c/${id}`);
	await socket;
	await expect(page.getByText('original reply')).toBeVisible();

	const before = await getChat(token, id);
	await patchHistory(token, id, {
		upsert: { 'assistant-1': { content: 'server won first' } },
		expected_revision: before.meta?.revision ?? 0
	});

	const result = await patchHistory(token, id, {
		upsert: { 'assistant-1': { content: 'my local edit that must survive' } },
		expected_revision: before.meta?.revision ?? 0
	});
	expect(result.status).toBe(409);
	expect(JSON.stringify(result.body)).toMatch(/another user has edited the chat/i);
});
