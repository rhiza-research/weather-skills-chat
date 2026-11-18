// Signs in to a local stack and saves a screenshot of one page. Run by
// `scripts/preview.sh shot`; see wiki/Development.md.
//
//   node shot.cjs BASE_URL PAGE OUT_PNG EMAIL PASSWORD WIDTHxHEIGHT
const { chromium } = require('playwright');

const [base, pagePath, out, email, password, size] = process.argv.slice(2);
const [width, height] = size.split('x').map(Number);

(async () => {
	const browser = await chromium.launch();
	const page = await browser.newPage({ viewport: { width, height } });
	const response = await page.request.post(`${base}/api/v1/auths/signin`, {
		data: { email, password }
	});
	if (!response.ok()) {
		throw new Error(`Sign-in as ${email} failed: ${response.status()} ${await response.text()}`);
	}
	const { token } = await response.json();
	// The app reads its session from localStorage.token before it starts.
	await page.addInitScript((value) => localStorage.setItem('token', value), token);
	await page.goto(base + pagePath, { waitUntil: 'load' });
	// The chat keeps a websocket open, so the network may never go fully idle.
	await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {});
	await page.screenshot({ path: out });
	await browser.close();
	console.log(out);
})().catch((error) => {
	console.error(error.message);
	process.exit(1);
});
