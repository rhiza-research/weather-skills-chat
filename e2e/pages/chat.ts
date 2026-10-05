import { expect, type Page } from '@playwright/test';

/** The new-chat screen. The sidebar starts closed; opening it is part of the smoke check. */
export class ChatPage {
	constructor(private page: Page) {}

	async open() {
		await this.page.goto('/');
	}

	async expectComposer() {
		await expect(this.page.locator('#chat-input')).toBeVisible();
	}

	async openSidebar() {
		await this.page.locator('#sidebar-toggle-button').click();
		await expect(this.page.locator('#chat-search')).toBeVisible();
		await expect(this.page.locator('#sidebar-new-chat-button')).toBeVisible();
	}
}
