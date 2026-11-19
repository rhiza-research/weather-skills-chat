import { expect, test } from '@playwright/test';

test('the settings modal is an accessible dialog', async ({ page }) => {
	await page.goto('/');
	const trigger = page.getByRole('button', { name: 'User Menu' }).locator('visible=true').first();
	await trigger.click();
	await page.getByText('Settings', { exact: true }).click();

	const dialog = page.getByRole('dialog', { name: 'Settings' });
	await expect(dialog).toBeVisible();
	await expect(dialog.locator(':focus')).toHaveCount(1);

	for (let i = 0; i < 25; i++) {
		await page.keyboard.press('Tab');
		await expect(dialog.locator(':focus')).toHaveCount(1);
	}

	await expect(dialog.getByRole('button', { name: 'General' })).toHaveAttribute(
		'aria-current',
		'true'
	);
	await dialog.getByRole('button', { name: 'Interface' }).click();
	await expect(dialog.getByRole('heading', { name: 'Chat', exact: true })).toBeVisible();
	await expect(dialog.getByRole('button', { name: /^Landing Page Mode: / })).toBeVisible();
	await expect(dialog.getByRole('switch', { name: 'Chat Bubble UI' })).toBeVisible();

	await page.keyboard.press('Escape');
	await expect(dialog).toBeHidden();
	await expect(trigger).toBeFocused();
});
