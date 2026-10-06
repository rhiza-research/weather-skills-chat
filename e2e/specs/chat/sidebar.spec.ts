import { expect, test, type Page } from '@playwright/test';
import { ageChat, clearChats, seedChat, sendTurn } from '../../chats';

const RANGES = new Set(['Today', 'Yesterday', 'Previous 7 days', 'Previous 30 days']);

async function waitForSocket(page: Page) {
	await page.waitForEvent('websocket', {
		predicate: (socket) => socket.url().includes('socket.io'),
		timeout: 20_000
	});
}

async function openSidebar(page: Page) {
	const sidebar = page.locator('#sidebar');
	if (await sidebar.locator('a[href^="/c/"]').first().isVisible().catch(() => false)) return;
	await page.locator('#sidebar-toggle-button').click();
	await expect(sidebar.locator('a[href^="/c/"]').first()).toBeVisible();
}

async function listing(page: Page) {
	return page.evaluate((ranges) => {
		const sidebar = document.getElementById('sidebar');
		const sections: string[] = [];
		const chats: { id: string; title: string; section: string }[] = [];
		if (!sidebar) return { sections, chats };
		let section = '';
		const walk = (node: Element) => {
			if (node instanceof HTMLAnchorElement) {
				const href = node.getAttribute('href') || '';
				if (href.startsWith('/c/')) {
					chats.push({
						id: href.slice('/c/'.length),
						title: (node.textContent || '').replace(/\s+/g, ' ').trim(),
						section
					});
				}
				return;
			}
			if (node instanceof HTMLButtonElement) {
				const label = (node.textContent || '').replace(/\s+/g, ' ').trim();
				if (ranges.includes(label)) {
					sections.push(label);
					section = label;
				}
			}
			for (const child of node.children) walk(child);
		};
		walk(sidebar);
		return { sections, chats };
	}, [...RANGES]);
}

function expectOneSection(rows: { sections: string[] }, name: string) {
	expect(rows.sections.filter((section) => section === name)).toHaveLength(1);
}

test('chatting with an older chat moves it into Today on every open page', async ({ page }) => {
	await clearChats();
	const today = await seedChat('listed today', 'today reply');
	const extraToday = await seedChat('also today', 'another today reply');
	const moving = await seedChat('moves to today', 'older reply');
	const staying = await seedChat('stays previous', 'still previous');
	await ageChat(staying.token, staying.id, 3);
	await ageChat(moving.token, moving.id, 5);

	const other = await page.context().newPage();
	const thisSocket = waitForSocket(page);
	const otherSocket = waitForSocket(other);
	await page.goto(`/c/${moving.id}`);
	await other.goto(`/c/${today.id}`);
	await thisSocket;
	await otherSocket;
	await openSidebar(page);
	await openSidebar(other);

	await expect.poll(async () => (await listing(page)).chats.some((chat) => chat.id === moving.id)).toBe(
		true
	);
	for (const tab of [page, other]) {
		const before = await listing(tab);
		expectOneSection(before, 'Today');
		expectOneSection(before, 'Previous 7 days');
		const moved = before.chats.filter((chat) => chat.id === moving.id);
		expect(moved).toHaveLength(1);
		expect(moved[0].section).toBe('Previous 7 days');
		expect(before.chats.find((chat) => chat.id === staying.id)?.section).toBe('Previous 7 days');
		expect(before.chats.find((chat) => chat.id === today.id)?.section).toBe('Today');
	}

	await sendTurn(moving.token, moving.id, 'bump this chat into today');

	for (const tab of [page, other]) {
		await expect
			.poll(async () => {
				const after = await listing(tab);
				const copies = after.chats.filter((chat) => chat.id === moving.id);
				return {
					todays: after.sections.filter((section) => section === 'Today').length,
					previous: after.sections.filter((section) => section === 'Previous 7 days').length,
					copies: copies.length,
					section: copies[0]?.section ?? '',
					firstToday: after.chats.find((chat) => chat.section === 'Today')?.id ?? ''
				};
			})
			.toEqual({
				todays: 1,
				previous: 1,
				copies: 1,
				section: 'Today',
				firstToday: moving.id
			});
		const after = await listing(tab);
		expect(after.chats.find((chat) => chat.id === staying.id)?.section).toBe('Previous 7 days');
		expect(after.chats.find((chat) => chat.id === today.id)?.section).toBe('Today');
	}
});
