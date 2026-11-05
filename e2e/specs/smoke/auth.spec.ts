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

test('requesting access confirms the request without signing in', async ({ page }) => {
	const auth = new AuthPage(page);
	await auth.open();
	await page.getByRole('button', { name: 'Request access' }).click();
	await expect(page.getByText(/^Request access to /)).toBeVisible();

	await page.getByPlaceholder('Enter Your Full Name').fill('Pending Person');
	await page.locator('input[name="email"]').fill(`pending-${Date.now()}@example.com`);
	await page.getByPlaceholder('Tell us who you are').fill('Testing access requests.');
	await page.locator('input[name="current-password"]').fill('password');
	await page.locator('button[type="submit"]').click();

	await expect(page.getByText('Request sent')).toBeVisible();
	await expect(page.getByText(/once your access is approved/)).toBeVisible();
	await expect(page.getByText(/logged in/i)).toHaveCount(0);
	await expect(page).toHaveURL(/\/auth/);
	expect(await page.evaluate(() => localStorage.getItem('token'))).toBeNull();

	await page.getByRole('button', { name: 'Back to sign in' }).click();
	await expect(page.getByText(/^Sign in to /)).toBeVisible();
});
