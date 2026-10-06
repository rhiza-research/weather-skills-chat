import { expect, test, type Page, type Route } from '@playwright/test';
import { seedChat, uploadArtifact } from '../../chats';

const LINE = 'paragraph 40';

async function placeLine(page: Page, text: string, top: number) {
	await page.evaluate(
		({ text, top }) => {
			const container = document.getElementById('messages-container');
			if (!container) throw new Error('messages container missing');
			const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
			let node: Node | null;
			while ((node = walker.nextNode())) {
				if (!node.textContent?.includes(text)) continue;
				const range = document.createRange();
				range.selectNodeContents(node);
				const rect = range.getBoundingClientRect();
				const box = container.getBoundingClientRect();
				container.scrollTop += rect.top - box.top - top;
				return;
			}
			throw new Error(`missing text ${text}`);
		},
		{ text, top }
	);
}

async function lineOffset(page: Page, text: string) {
	return page.evaluate((text) => {
		const container = document.getElementById('messages-container');
		if (!container) return null;
		const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
		let node: Node | null;
		while ((node = walker.nextNode())) {
			if (!node.textContent?.includes(text)) continue;
			const range = document.createRange();
			range.selectNodeContents(node);
			return range.getBoundingClientRect().top - container.getBoundingClientRect().top;
		}
		return null;
	}, text);
}

async function placeImage(page: Page, alt: string, top: number) {
	await page.evaluate(
		({ alt, top }) => {
			const container = document.getElementById('messages-container');
			const image = container?.querySelector<HTMLElement>(`img[alt="${alt}"]`);
			if (!container || !image) throw new Error(`missing image ${alt}`);
			const rect = image.getBoundingClientRect();
			const box = container.getBoundingClientRect();
			container.scrollTop += rect.top - box.top - top;
		},
		{ alt, top }
	);
}

async function placeImageAt(page: Page, index: number, top: number) {
	await page.evaluate(
		({ index, top }) => {
			const container = document.getElementById('messages-container');
			const image = container?.querySelectorAll<HTMLElement>('img[alt="panel"]')[index];
			if (!container || !image) throw new Error(`missing panel ${index}`);
			const rect = image.getBoundingClientRect();
			const box = container.getBoundingClientRect();
			container.scrollTop += rect.top - box.top - top;
		},
		{ index, top }
	);
}

async function imageOffsetAt(page: Page, index: number) {
	return page.evaluate((index) => {
		const container = document.getElementById('messages-container');
		const image = container?.querySelectorAll('img[alt="panel"]')[index];
		if (!container || !image) return null;
		return image.getBoundingClientRect().top - container.getBoundingClientRect().top;
	}, index);
}

async function imageOffset(page: Page, alt: string) {
	return page.evaluate((alt) => {
		const container = document.getElementById('messages-container');
		const image = container?.querySelector(`img[alt="${alt}"]`);
		if (!container || !image) return null;
		return image.getBoundingClientRect().top - container.getBoundingClientRect().top;
	}, alt);
}

async function distanceFromBottom(page: Page) {
	return page.evaluate(() => {
		const container = document.getElementById('messages-container');
		if (!container) return 9999;
		return container.scrollHeight - container.scrollTop - container.clientHeight;
	});
}

/** Open the sidebar if it is closed. Do not toggle it closed; that resizes images. */
async function ensureSidebar(page: Page) {
	const newChat = page.locator('#sidebar-new-chat-button');
	if (await newChat.isVisible()) return;
	await page.locator('#sidebar-toggle-button').click();
	await expect(newChat).toBeVisible();
}

/** Leave the chat and come back without reloading the page, so the saved position survives. */
async function leaveAndReturn(page: Page, id: string) {
	await ensureSidebar(page);
	await page.locator('#sidebar-new-chat-button').click();
	await expect(page.locator('#chat-input')).toBeVisible();
	await page.locator(`a[href="/c/${id}"]`).click();
	await expect(page).toHaveURL(new RegExp(`/c/${id}$`));
	await expect(page.locator('#messages-container')).toBeVisible();
}

async function waitForImages(page: Page, selector: string, count: number) {
	await page.waitForFunction(
		({ selector, count }) => {
			const images = [...document.querySelectorAll<HTMLImageElement>(selector)];
			return images.length >= count && images.every((image) => image.complete && image.naturalHeight > 100);
		},
		{ selector, count }
	);
}

test('a chat left at the bottom returns to the latest line immediately', async ({ page }) => {
	const panels = Array.from({ length: 18 }, () => '![panel](panel.svg)').join('\n\n');
	const { id, token } = await seedChat('bottom panels', panels);
	await uploadArtifact(
		token,
		id,
		'panel.svg',
		Buffer.from(
			'<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480"><rect width="640" height="480" fill="#9bb"/></svg>'
		),
		'image/svg+xml'
	);
	await page.goto('/');
	await page.context().addCookies([
		{ name: 'token', value: token, url: new URL(page.url()).origin }
	]);
	await page.goto(`/c/${id}`);
	await waitForImages(page, 'img[alt="panel"]', 18);
	await ensureSidebar(page);
	await placeImageAt(page, 7, 48);
	await page.waitForTimeout(250);
	const savedImage = await imageOffsetAt(page, 7);
	expect(savedImage).not.toBeNull();

	await page.evaluate(() => {
		const container = document.getElementById('messages-container');
		if (!container) throw new Error('messages container missing');
		container.scrollTop = container.scrollHeight;
	});
	await page.waitForTimeout(250);
	expect(await distanceFromBottom(page)).toBeLessThan(24);

	let release = () => {};
	const held = new Promise<void>((resolve) => {
		release = resolve;
	});
	const holdGet = async (route: Route) => {
		if (route.request().method() !== 'GET') {
			await route.continue();
			return;
		}
		await held;
		await route.continue();
	};
	await page.route(`**/api/v1/chats/${id}`, holdGet);
	await page.route(`**/api/v1/chats/${id}/tags`, holdGet);
	await page.route('**/api/v1/users/user/settings', holdGet);
	await page.route(`**/api/tasks/chat/${id}`, holdGet);

	try {
		await leaveAndReturn(page, id);
		await waitForImages(page, 'img[alt="panel"]', 18);
		expect(await distanceFromBottom(page)).toBeLessThan(24);
	} finally {
		release();
		await page.unroute(`**/api/v1/chats/${id}`);
		await page.unroute(`**/api/v1/chats/${id}/tags`);
		await page.unroute('**/api/v1/users/user/settings');
		await page.unroute(`**/api/tasks/chat/${id}`);
	}
});

test('a long message returns to the same line', async ({ page }) => {
	const paragraphs = Array.from({ length: 150 }, (_, index) => {
		const n = index + 1;
		return `paragraph ${n} stays on this line of the reply.`;
	}).join('\n\n');
	const { id } = await seedChat('long reply', paragraphs);

	await page.goto(`/c/${id}`);
	await expect(page.getByText(LINE, { exact: false }).first()).toBeAttached();
	await placeLine(page, LINE, 48);
	await page.waitForTimeout(250);
	const before = await lineOffset(page, LINE);
	expect(before).not.toBeNull();

	await leaveAndReturn(page, id);
	await expect(page.getByText(LINE, { exact: false }).first()).toBeAttached();
	await page.waitForTimeout(400);
	const after = await lineOffset(page, LINE);

	expect(Math.abs((after ?? 0) - (before ?? 0))).toBeLessThan(24);
});

test('a message full of images returns to the same image', async ({ page }) => {
	const alt = 'image 8';
	await page.route('**/e2e-tall.svg*', (route) =>
		route.fulfill({
			contentType: 'image/svg+xml',
			body: `<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480"><rect width="640" height="480" fill="#d0d0d0"/></svg>`
		})
	);
	const panels = Array.from({ length: 18 }, (_, index) => {
		const n = index + 1;
		return `![image ${n}](/e2e-tall.svg?n=${n})`;
	}).join('\n\n');
	const { id } = await seedChat('image reply', panels);

	await page.goto(`/c/${id}`);
	await waitForImages(page, 'img[alt^="image "]', 18);
	await ensureSidebar(page);
	await placeImage(page, alt, 48);
	await page.waitForTimeout(250);
	const before = await imageOffset(page, alt);
	expect(before).not.toBeNull();

	await leaveAndReturn(page, id);
	await waitForImages(page, 'img[alt^="image "]', 18);
	await expect
		.poll(async () => Math.abs((await imageOffset(page, alt) ?? 0) - (before ?? 0)), {
			timeout: 1_000
		})
		.toBeLessThan(24);
});

test('repeated copies of one artifact image return to the same copy', async ({ page }) => {
	const copy = 7;
	const panels = Array.from({ length: 18 }, () => '![panel](panel.svg)').join('\n\n');
	const { id, token } = await seedChat('artifact panels', panels);
	await uploadArtifact(
		token,
		id,
		'panel.svg',
		Buffer.from(
			'<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480"><rect width="640" height="480" fill="#9bb"/></svg>'
		),
		'image/svg+xml'
	);
	await page.goto('/');
	await page.context().addCookies([
		{ name: 'token', value: token, url: new URL(page.url()).origin }
	]);

	await page.goto(`/c/${id}`);
	await waitForImages(page, 'img[alt="panel"]', 18);
	await ensureSidebar(page);
	await placeImageAt(page, copy, 48);
	await page.waitForTimeout(250);
	const before = await imageOffsetAt(page, copy);
	expect(before).not.toBeNull();

	let releaseChat: (() => void) | null = null;
	const chatHeld = new Promise<void>((resolve) => {
		releaseChat = resolve;
	});
	await page.route(`**/api/v1/chats/${id}`, async (route) => {
		if (route.request().method() !== 'GET') {
			await route.continue();
			return;
		}
		await chatHeld;
		await route.continue();
	});

	await leaveAndReturn(page, id);
	await waitForImages(page, 'img[alt="panel"]', 18);
	try {
		await expect
			.poll(
				async () => {
					const after = await imageOffsetAt(page, copy);
					return Math.abs((after ?? 0) - (before ?? 0));
				},
				{ timeout: 1_000 }
			)
			.toBeLessThan(24);
	} finally {
		releaseChat?.();
		await page.unroute(`**/api/v1/chats/${id}`);
	}
});
