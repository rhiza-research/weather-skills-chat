import { expect, test } from '@playwright/test';
import { seedChat, uploadArtifact } from '../../chats';
import { openSidebar, waitForSocket } from '../../helpers';

// A 1x1 PNG: the card shows only image responses of a plausible size.
const PNG = Buffer.from(
	'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==',
	'base64'
);

const displayImage = (id: string, path: string) => {
	const attr = (value: unknown) => JSON.stringify(value).replace(/"/g, '&quot;');
	return `<details type="tool_calls" done="true" id="${id}" name="display_image" arguments="${attr({ path })}" result="${attr(`Showing ${path}`)}">\n<summary>Tool Executed</summary>\n</details>`;
};

test('display_image cards never load from the chat opened after theirs', async ({ page }) => {
	const shown = await seedChat(
		'display image source',
		['Here it is.', displayImage('call-1', 'plot.png'), displayImage('call-2', 'plot.png')].join(
			'\n'
		)
	);
	await uploadArtifact(shown.token, shown.id, 'plot.png', PNG, 'image/png');
	const other = await seedChat('display image other', 'No images here.');

	const wrongChat: string[] = [];
	page.on('request', (request) => {
		if (
			request.url().includes(`/chats/${other.id}/artifacts`) &&
			request.url().includes('plot.png')
		) {
			wrongChat.push(request.url());
		}
	});

	const socket = waitForSocket(page);
	await page.goto(`/c/${shown.id}`);
	await socket;
	await expect(page.locator('img[alt="plot.png"]')).toHaveCount(2, {
		timeout: 15_000
	});

	await openSidebar(page);
	await page.locator(`a[href="/c/${other.id}"]`).click();
	await expect(page.getByText('No images here.')).toBeVisible();
	// Past the cards' last retry (0.4 + 0.8 + 1.6 s).
	await page.waitForTimeout(3_500);
	expect(wrongChat).toEqual([]);
});
