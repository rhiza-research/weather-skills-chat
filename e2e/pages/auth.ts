import type { Page } from '@playwright/test';

export class AuthPage {
	constructor(private page: Page) {}

	async open() {
		await this.page.goto('/auth');
	}

	async signIn(email: string, password: string) {
		await this.page.locator('input[name="email"]').fill(email);
		await this.page.locator('input[name="current-password"]').fill(password);
		await this.page.locator('button[type="submit"]').click();
	}
}
