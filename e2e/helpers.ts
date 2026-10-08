import { expect, type Page } from '@playwright/test';

const RANGES = new Set(['Today', 'Yesterday', 'Previous 7 days', 'Previous 30 days']);

export async function waitForSocket(page: Page) {
	await page.waitForEvent('websocket', {
		predicate: (socket) => socket.url().includes('socket.io'),
		timeout: 20_000
	});
}

export async function openSidebar(page: Page) {
	const sidebar = page.locator('#sidebar');
	if (await sidebar.locator('a[href^="/c/"]').first().isVisible().catch(() => false)) return;
	await page.locator('#sidebar-toggle-button').click();
	await expect(sidebar.locator('a[href^="/c/"]').first()).toBeVisible();
}

export async function listing(page: Page) {
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

export function watchChatGets(page: Page, id: string) {
	const hits: string[] = [];
	page.on('request', (request) => {
		if (request.method() !== 'GET') return;
		const path = new URL(request.url()).pathname;
		if (path === `/api/v1/chats/${id}`) hits.push(request.url());
	});
	return hits;
}
