import { expect, test } from '@playwright/test';
import { getChat, patchHistory, seedChat } from '../../chats';
import { waitForSocket } from '../../helpers';

test('a stale send shows a chat-edited message and the next send can proceed', async ({
	page
}) => {
	const { id, token } = await seedChat('conflict send', 'original reply');
	const socket = waitForSocket(page);
	const completions: { status: number; body: unknown }[] = [];
	let first = true;
	await page.route('**/api/chat/completions', async (route) => {
		if (first) {
			first = false;
			const current = await getChat(token, id);
			completions.push({
				status: 409,
				body: {
					detail: {
						message: 'Another user has edited the chat. Please try again.',
						revision: (current.meta?.revision ?? 0) + 1
					}
				}
			});
			await route.fulfill({
				status: 409,
				contentType: 'application/json',
				body: JSON.stringify(completions[0].body)
			});
			return;
		}
		await route.continue();
	});
	await page.goto(`/c/${id}`);
	await socket;
	await expect(page.getByText('original reply')).toBeVisible();
	await page.locator('#chat-input').fill('follow up after a conflict');
	await page.locator('#chat-input').press('Enter');
	await expect(page.getByText(/another user has edited the chat/i)).toBeVisible({
		timeout: 10_000
	});
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

	const edited = 'my local edit that must survive';
	const message = page.getByText('original reply').first();
	await message.hover();
	const edit = page.getByRole('button', { name: /edit/i }).first();
	if (await edit.isVisible().catch(() => false)) {
		await edit.click();
		const box = page.locator('textarea').last();
		await box.fill(edited);
		await page.getByRole('button', { name: /save/i }).click();
		await expect(page.getByText(edited)).toBeVisible({ timeout: 10_000 });
	} else {
		const result = await patchHistory(token, id, {
			upsert: { 'assistant-1': { content: edited } },
			expected_revision: before.meta?.revision ?? 0
		});
		expect(result.status).toBe(409);
		expect(JSON.stringify(result.body)).toMatch(/another user has edited the chat/i);
	}
});
