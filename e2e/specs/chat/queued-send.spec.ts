import { expect, test, type Page } from '@playwright/test';
import { seedChat } from '../../chats';
import { waitForSocket } from '../../helpers';

// Completion requests are answered with a task id and nothing else, so the
// reply stays running until the user stops it.
async function holdReplies(page: Page) {
	const sent: string[] = [];
	await page.route('**/api/chat/completions', async (route) => {
		const body = route.request().postDataJSON();
		sent.push(body?.turn?.user_message?.content ?? '');
		await route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify({ status: true, task_id: `e2e-task-${sent.length}` })
		});
	});
	await page.route('**/api/tasks/stop/**', (route) =>
		route.fulfill({ status: 200, contentType: 'application/json', body: '{"status":true}' })
	);
	return sent;
}

async function openChat(page: Page, id: string) {
	const socket = waitForSocket(page);
	await page.goto(`/c/${id}`);
	await socket;
	await expect(page.locator('#chat-input')).toBeVisible();
}

async function send(page: Page, text: string) {
	const input = page.locator('#chat-input');
	await input.fill(text);
	await input.press('Enter');
}

const queuedRows = (page: Page) => page.locator('#queued-sends .queued-send');
const queuedTexts = (page: Page) => page.locator('#queued-sends .queued-send-text');
const stop = (page: Page) => page.getByRole('button', { name: 'Stop' });

test('up to three sends queue while the reply runs, and go out one per turn', async ({
	page
}) => {
	const { id } = await seedChat('queued send', 'first reply');
	const sent = await holdReplies(page);
	await openChat(page, id);

	await send(page, 'first question');
	await expect.poll(() => sent.length).toBe(1);
	await expect(stop(page)).toBeVisible();

	for (const text of ['queued one', 'queued two', 'queued three']) await send(page, text);
	await expect(queuedTexts(page)).toHaveText(['queued one', 'queued two', 'queued three']);
	await expect(page.locator('#chat-input')).toHaveText('');

	await send(page, 'one too many');
	const limitToast = page.locator('[data-sonner-toast]', {
		hasText: 'Only 3 sends can be queued.'
	});
	await expect(limitToast).toBeVisible();
	await expect(queuedRows(page)).toHaveCount(3);
	await limitToast.getByRole('button', { name: 'Close toast' }).click();
	await expect(limitToast).toHaveCount(0);

	await stop(page).click();
	await expect.poll(() => sent).toEqual(['first question', 'queued one']);
	await expect(queuedTexts(page)).toHaveText(['queued two', 'queued three']);

	await stop(page).click();
	await expect.poll(() => sent.at(-1)).toBe('queued two');
	await stop(page).click();
	await expect.poll(() => sent.at(-1)).toBe('queued three');
	await expect(page.locator('#queued-sends')).toHaveCount(0);
	expect(sent).toEqual(['first question', 'queued one', 'queued two', 'queued three']);
});

test('one queued send can be deleted and the rest still go out', async ({ page }) => {
	const { id } = await seedChat('queued delete', 'first reply');
	const sent = await holdReplies(page);
	await openChat(page, id);

	await send(page, 'first question');
	await expect.poll(() => sent.length).toBe(1);
	for (const text of ['keep one', 'never mind', 'keep two']) await send(page, text);
	await expect(queuedRows(page)).toHaveCount(3);

	await queuedRows(page)
		.nth(1)
		.getByRole('button', { name: 'Delete queued send' })
		.click();
	await expect(queuedTexts(page)).toHaveText(['keep one', 'keep two']);

	await stop(page).click();
	await expect.poll(() => sent.at(-1)).toBe('keep one');
	await stop(page).click();
	await expect.poll(() => sent.at(-1)).toBe('keep two');
	await stop(page).click();
	await expect(stop(page)).toHaveCount(0);
	expect(sent).toEqual(['first question', 'keep one', 'keep two']);
});

test('send now stops the reply and sends that queued send next', async ({ page }) => {
	const { id } = await seedChat('queued send now', 'first reply');
	const sent = await holdReplies(page);
	await openChat(page, id);

	await send(page, 'first question');
	await expect.poll(() => sent.length).toBe(1);
	for (const text of ['later one', 'later two', 'urgent']) await send(page, text);
	await expect(queuedRows(page)).toHaveCount(3);

	await queuedRows(page).nth(2).getByRole('button', { name: 'Send now' }).click();
	await expect.poll(() => sent).toEqual(['first question', 'urgent']);
	await expect(queuedTexts(page)).toHaveText(['later one', 'later two']);
	await expect(stop(page)).toBeVisible();

	await stop(page).click();
	await expect.poll(() => sent.at(-1)).toBe('later one');
	await expect(queuedTexts(page)).toHaveText(['later two']);
});

test('queued sends stay with their chat when the user opens another chat', async ({ page }) => {
	const first = await seedChat('queued keeps', 'first reply');
	const other = await seedChat('queued elsewhere', 'other reply');
	const sent = await holdReplies(page);
	await openChat(page, first.id);

	await send(page, 'first question');
	await expect.poll(() => sent.length).toBe(1);
	await send(page, 'waiting one');
	await send(page, 'waiting two');
	await expect(queuedRows(page)).toHaveCount(2);

	await page.locator('#sidebar-toggle-button').click();
	await page.locator(`#sidebar a[href="/c/${other.id}"]`).click();
	await expect(page.getByText('other reply')).toBeVisible();
	await expect(page.locator('#queued-sends')).toHaveCount(0);

	await page.locator(`#sidebar a[href="/c/${first.id}"]`).click();
	await expect(page.getByText('first reply')).toBeVisible();
	await expect(queuedTexts(page)).toHaveText(['waiting one', 'waiting two']);
	expect(sent).toEqual(['first question']);

	await stop(page).click();
	await expect.poll(() => sent).toEqual(['first question', 'waiting one']);
	await expect(queuedTexts(page)).toHaveText(['waiting two']);
});
