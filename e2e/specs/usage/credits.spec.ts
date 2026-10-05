import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import { adminAccount } from '../../accounts';
import { ChatPage } from '../../pages/chat';

const authHeaders = (token: string) => ({
	Authorization: `Bearer ${token}`
});

async function tokenFromPage(page: Page) {
	const token = await page.evaluate(() => localStorage.getItem('token'));
	expect(token, 'signed-in session token').toBeTruthy();
	return token as string;
}

/** A workspace the bootstrap admin owns, with a limit, so the non-admin counters have a cap. */
async function workspaceWithLimit(request: APIRequestContext, token: string) {
	const name = `Credits ${Date.now()}`;
	const created = await request.post('/api/v1/organizations/', {
		headers: authHeaders(token),
		data: { name }
	});
	expect(created.ok(), await created.text()).toBeTruthy();
	const org = await created.json();

	const activated = await request.post(`/api/v1/organizations/${org.id}/activate`, {
		headers: authHeaders(token)
	});
	expect(activated.ok(), await activated.text()).toBeTruthy();

	const limited = await request.post(`/api/v1/organizations/${org.id}/update`, {
		headers: authHeaders(token),
		data: { monthly_limit_usd: 10 }
	});
	expect(limited.ok(), await limited.text()).toBeTruthy();
	return { id: org.id as string, name };
}

async function openUserMenu(page: Page) {
	const chat = new ChatPage(page);
	await chat.openSidebar();
	await page.getByRole('button', { name: adminAccount.name }).click();
}

test('a user sees usage in credits, not dollars', async ({ page }) => {
	const chat = new ChatPage(page);
	await chat.open();
	const token = await tokenFromPage(page);
	const org = await workspaceWithLimit(page.request, token);

	await page.evaluate((orgId) => {
		localStorage.setItem('activeOrganizationId', orgId);
	}, org.id);
	await page.reload();
	await chat.expectComposer();

	await openUserMenu(page);
	const menuUsage = page.getByText(/0\.00\s*\/\s*10\.00\s+credits/);
	await expect(menuUsage).toBeVisible();
	await expect(menuUsage).not.toContainText('$');

	await page.getByRole('link', { name: 'Organization settings' }).click();
	await expect(page).toHaveURL(/\/organization/);
	const orgUsage = page.getByText(/0\.00\s*\/\s*10\.00\s+credits/);
	const remaining = page.getByText(/10\.00\s+remaining credits/);
	await expect(orgUsage.first()).toBeVisible();
	await expect(remaining).toBeVisible();
	await expect(page.locator('body')).not.toContainText('$');
});
