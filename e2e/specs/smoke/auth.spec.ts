import { expect, test } from '@playwright/test';
import { adminAccount } from '../../accounts';
import { AuthPage } from '../../pages/auth';

test('a signed-out visit stays on the sign-in page', async ({ page }) => {
	await page.goto('/');
	await expect(page).toHaveURL(/\/auth/);
	await expect(page.locator('input[name="email"]')).toBeVisible();
	await expect(page.locator('button[type="submit"]')).toBeVisible();
});

test('a wrong password stays on the sign-in page', async ({ page }) => {
	const auth = new AuthPage(page);
	await auth.open();
	await auth.signIn(adminAccount.email, 'not-the-password');
	await expect(page).toHaveURL(/\/auth/);
	await expect(page.getByText(/email or password provided is incorrect/i)).toBeVisible();
});
