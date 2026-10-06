import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { request, type FullConfig } from '@playwright/test';
import { adminAccount } from './accounts';

const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

async function globalSetup(_config: FullConfig) {
	const baseURL = process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:3000';
	const apiURL = process.env.PLAYWRIGHT_API_URL || baseURL;

	const api = await request.newContext({ baseURL: apiURL });
	const deadline = Date.now() + 120_000;
	let last = 'app did not become ready';

	try {
		while (Date.now() < deadline) {
			const health = await api.get('/health').catch(() => null);
			if (!health?.ok()) {
				last = `health ${health?.status() ?? 'down'}`;
				await wait(2_000);
				continue;
			}
			const signin = await api
				.post('/api/v1/auths/signin', {
					data: { email: adminAccount.email, password: adminAccount.password }
				})
				.catch(() => null);
			if (signin?.ok()) {
				const body = await signin.json();
				if (!body?.token) throw new Error('sign-in response had no token');
				const authDir = path.join(path.dirname(fileURLToPath(import.meta.url)), '.auth');
				fs.mkdirSync(authDir, { recursive: true });
				fs.writeFileSync(
					path.join(authDir, 'admin.json'),
					JSON.stringify(
						{
							cookies: [],
							origins: [
								{
									origin: new URL(baseURL).origin,
									localStorage: [
										{ name: 'token', value: body.token },
										{ name: 'locale', value: 'en-US' }
									]
								}
							]
						},
						null,
						2
					)
				);
				return;
			}
			last = `sign-in ${signin?.status() ?? 'failed'}`;
			await wait(2_000);
		}
		throw new Error(last);
	} finally {
		await api.dispose();
	}
}

export default globalSetup;
