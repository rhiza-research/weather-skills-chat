import { expect, test, type Page } from '@playwright/test';
import { seedChat } from '../../chats';
import {
	emitChatCompletion,
	hideTab,
	notificationPlays,
	waitForSocket,
	watchNotificationSound
} from '../../helpers';

async function openChat(page: Page, id: string) {
	const socket = waitForSocket(page);
	await page.goto(`/c/${id}`);
	await socket;
	await expect(page.locator('#chat-input')).toBeVisible();
	await page.locator('#chat-input').click();
}

test('a reply in the open chat does not play a sound while this tab is focused', async ({
	page
}) => {
	const { id } = await seedChat('notify focused chat', 'already there');
	await watchNotificationSound(page);
	await openChat(page, id);
	const before = await notificationPlays(page);
	await emitChatCompletion(page, id, 'notify focused chat');
	await page.waitForTimeout(500);
	expect(await notificationPlays(page)).toBe(before);
});

test('a reply in another chat plays a sound while this tab is focused', async ({
	page
}) => {
	const open = await seedChat('notify this chat', 'this reply');
	const other = await seedChat('notify other chat', 'other reply');
	await watchNotificationSound(page);
	await openChat(page, open.id);
	const before = await notificationPlays(page);
	await emitChatCompletion(page, other.id, 'notify other chat');
	await expect.poll(() => notificationPlays(page), { timeout: 5_000 }).toBeGreaterThan(before);
});

test('a reply plays a sound when this tab is in the background', async ({ page }) => {
	const { id } = await seedChat('notify background', 'already there');
	await watchNotificationSound(page);
	await openChat(page, id);
	const before = await notificationPlays(page);
	await hideTab(page);
	await emitChatCompletion(page, id, 'notify background');
	await expect.poll(() => notificationPlays(page), { timeout: 5_000 }).toBeGreaterThan(before);
});
