import { test } from '@playwright/test';
import { ChatPage } from '../../pages/chat';

test('a signed-in user lands on a new chat', async ({ page }) => {
	const chat = new ChatPage(page);
	await chat.open();
	await chat.expectComposer();
	await chat.openSidebar();
});
