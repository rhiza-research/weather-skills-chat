import { expect, test } from '@playwright/test';
import { ageChat, clearChats, seedChat, sendTurn } from '../../chats';
import { listing, openSidebar, waitForSocket } from '../../helpers';

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

	const ids = [today.id, extraToday.id, moving.id, staying.id];
	for (const tab of [page, other]) {
		await expect
			.poll(async () => {
				const rows = await listing(tab);
				return ids.every((id) => rows.chats.some((chat) => chat.id === id));
			})
			.toBe(true);
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
