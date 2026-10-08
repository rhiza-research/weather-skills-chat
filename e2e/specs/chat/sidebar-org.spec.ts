import { expect, test, type APIRequestContext } from '@playwright/test';
import { chatDocument, clearChats, replaceAssistant } from '../../chats';
import { listing, openSidebar, waitForSocket } from '../../helpers';

const authHeaders = (token: string) => ({ Authorization: `Bearer ${token}` });

async function tokenFromPage(page: { evaluate: (fn: () => string | null) => Promise<string | null> }) {
	const token = await page.evaluate(() => localStorage.getItem('token'));
	expect(token).toBeTruthy();
	return token as string;
}

async function createWorkspace(request: APIRequestContext, token: string, name: string) {
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
	return org.id as string;
}

async function seedOrgChat(
	request: APIRequestContext,
	token: string,
	orgId: string,
	title: string,
	assistant: string
) {
	const created = await request.post('/api/v1/chats/new', {
		headers: { ...authHeaders(token), 'x-organization-id': orgId },
		data: { chat: chatDocument(title, assistant), organization_id: orgId, visibility: 'private' }
	});
	expect(created.ok(), await created.text()).toBeTruthy();
	const body = await created.json();
	return body.id as string;
}

test('a chat:list row from another organization does not appear in this sidebar', async ({
	page
}) => {
	await page.goto('/');
	await clearChats();
	const token = await tokenFromPage(page);
	const orgA = await createWorkspace(page.request, token, `Org A ${Date.now()}`);
	const orgB = await createWorkspace(page.request, token, `Org B ${Date.now()}`);
	const chatA = await seedOrgChat(page.request, token, orgA, 'org A chat', 'a reply');
	const chatB = await seedOrgChat(page.request, token, orgB, 'org B chat', 'b reply');

	await page.evaluate((orgId) => localStorage.setItem('activeOrganizationId', orgId), orgA);
	const socket = waitForSocket(page);
	await page.goto(`/c/${chatA}`);
	await socket;
	await openSidebar(page);
	await expect.poll(async () => (await listing(page)).chats.some((chat) => chat.id === chatA)).toBe(
		true
	);

	await replaceAssistant(token, chatB, 'updated in the other org');

	await page.waitForTimeout(2000);
	const rows = await listing(page);
	expect(rows.chats.some((chat) => chat.id === chatB)).toBe(false);
	expect(rows.chats.some((chat) => chat.id === chatA)).toBe(true);
});
