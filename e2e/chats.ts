import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { request as playwrightRequest } from '@playwright/test';
import { adminAccount } from './accounts';

const apiOrigin = () =>
	process.env.PLAYWRIGHT_API_URL || process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:3000';

export type SeededChat = {
	id: string;
	token: string;
};

const message = (
	id: string,
	role: 'user' | 'assistant',
	content: string,
	parentId: string | null,
	childrenIds: string[]
) => ({
	id,
	role,
	content,
	parentId,
	childrenIds,
	done: true
});

/** A two-message chat whose assistant reply is the text under test. */
export function chatDocument(title: string, assistant: string) {
	return {
		title,
		models: [],
		history: {
			currentId: 'assistant-1',
			messages: {
				'user-1': message('user-1', 'user', 'Show the reading.', null, ['assistant-1']),
				'assistant-1': message('assistant-1', 'assistant', assistant, 'user-1', [])
			}
		}
	};
}

async function authed() {
	const api = await playwrightRequest.newContext({ baseURL: apiOrigin() });
	const signin = await api.post('/api/v1/auths/signin', {
		data: { email: adminAccount.email, password: adminAccount.password }
	});
	if (!signin.ok()) {
		throw new Error(`sign-in failed: ${signin.status()} ${await signin.text()}`);
	}
	const body = await signin.json();
	if (!body?.token) throw new Error('sign-in response had no token');
	return { api, token: body.token as string };
}

export async function seedChat(title: string, assistant: string): Promise<SeededChat> {
	const { api, token } = await authed();
	try {
		const created = await api.post('/api/v1/chats/new', {
			headers: { authorization: `Bearer ${token}` },
			data: { chat: chatDocument(title, assistant), visibility: 'private' }
		});
		if (!created.ok()) {
			throw new Error(`create chat failed: ${created.status()} ${await created.text()}`);
		}
		const body = await created.json();
		if (!body?.id) throw new Error('create chat response had no id');
		return { id: body.id as string, token };
	} finally {
		await api.dispose();
	}
}

/** Store one file in the chat's artifact sandbox. */
export async function uploadArtifact(
	token: string,
	id: string,
	path: string,
	body: Buffer,
	contentType: string
) {
	const api = await playwrightRequest.newContext({ baseURL: apiOrigin() });
	try {
		const uploaded = await api.post(`/api/v1/chats/${id}/artifacts`, {
			headers: { authorization: `Bearer ${token}` },
			multipart: {
				path,
				file: { name: path, mimeType: contentType, buffer: body }
			}
		});
		if (!uploaded.ok()) {
			throw new Error(`upload artifact failed: ${uploaded.status()} ${await uploaded.text()}`);
		}
	} finally {
		await api.dispose();
	}
}

/** A workspace model the chat screen can select and send with. */
export async function ensureChatModel(token: string) {
	const api = await playwrightRequest.newContext({ baseURL: apiOrigin() });
	try {
		const created = await api.post('/api/v1/models/create', {
			headers: {
				authorization: `Bearer ${token}`,
				'x-organization-id': 'platform'
			},
			data: {
				id: 'e2e-sender',
				base_model_id: 'e2e-base',
				name: 'E2E Sender',
				meta: {},
				params: {}
			}
		});
		if (created.ok()) return;
		const detail = await created.text();
		if (detail.includes('already registered')) return;
		throw new Error(`create model failed: ${created.status()} ${detail}`);
	} finally {
		await api.dispose();
	}
}

/** The same completion request a focused tab sends. */
export async function sendTurn(token: string, id: string, content: string) {
	await ensureChatModel(token);
	const api = await playwrightRequest.newContext({ baseURL: apiOrigin() });
	const userId = `user-${Date.now()}`;
	const assistantId = `assistant-${Date.now()}`;
	try {
		const sent = await api.post('/api/chat/completions', {
			headers: { authorization: `Bearer ${token}` },
			timeout: 20_000,
			data: {
				stream: true,
				model: 'e2e-sender',
				chat_id: id,
				id: assistantId,
				turn: {
					parent_id: 'assistant-1',
					user_message: {
						id: userId,
						parentId: 'assistant-1',
						childrenIds: [assistantId],
						role: 'user',
						content
					},
					assistant_message: {
						id: assistantId,
						parentId: userId,
						childrenIds: [],
						role: 'assistant',
						content: '',
						done: false,
						model: 'e2e-sender'
					}
				}
			}
		});
		if (!sent.ok()) {
			throw new Error(`send failed: ${sent.status()} ${await sent.text()}`);
		}
	} finally {
		await api.dispose();
	}
}

const sqlitePath = () => {
	const url = process.env.DATABASE_URL || '';
	if (url.startsWith('sqlite:///')) return url.slice('sqlite:///'.length);
	return path.join(path.dirname(fileURLToPath(import.meta.url)), '.data/webui.db');
};

function sqliteRun(sql: string, args: Array<string | number> = []) {
	const script = `
import sqlite3, sys, json
conn = sqlite3.connect(sys.argv[1])
sql = sys.argv[2]
args = json.loads(sys.argv[3])
n = conn.execute(sql, args).rowcount
conn.commit()
print(n)
`;
	const container = process.env.E2E_SQLITE_CONTAINER;
	const db = container
		? process.env.E2E_SQLITE || '/app/backend/data/webui.db'
		: sqlitePath();
	const ran = container
		? spawnSync(
				'docker',
				['exec', container, 'python', '-c', script, db, sql, JSON.stringify(args)],
				{ encoding: 'utf8' }
			)
		: spawnSync('python3', ['-c', script, db, sql, JSON.stringify(args)], { encoding: 'utf8' });
	if (ran.status !== 0) {
		throw new Error(`sqlite failed: ${ran.stderr || ran.stdout}`);
	}
	return Number((ran.stdout || '').trim());
}

/** Keep the first-page sidebar list small so aged chats stay visible. */
export function clearChats() {
	sqliteRun('DELETE FROM chat');
}

/** Move a chat onto a past calendar day so the sidebar lists it under an older range. */
export async function ageChat(token: string, id: string, daysAgo: number) {
	const unix = Math.floor(Date.now() / 1000) - daysAgo * 24 * 3600;
	for (let attempt = 0; attempt < 8; attempt++) {
		const n = sqliteRun('UPDATE chat SET updated_at = ?, created_at = ? WHERE id = ?', [
			unix,
			unix,
			id
		]);
		if (n !== 1) throw new Error(`aged ${n} rows for ${id}`);
		await new Promise((resolve) => setTimeout(resolve, 200));
		const api = await playwrightRequest.newContext({ baseURL: apiOrigin() });
		try {
			const got = await api.get(`/api/v1/chats/${id}`, {
				headers: { authorization: `Bearer ${token}` }
			});
			if (!got.ok()) {
				throw new Error(`get chat failed: ${got.status()} ${await got.text()}`);
			}
			const row = (await got.json()) as { updated_at: number };
			if (Math.abs(row.updated_at - unix) < 2) return;
		} finally {
			await api.dispose();
		}
	}
	throw new Error(`chat ${id} would not stay aged`);
}

/** Replace the assistant message. This commits the chat and emits chat:updated. */
export async function replaceAssistant(token: string, id: string, content: string) {
	const api = await playwrightRequest.newContext({ baseURL: apiOrigin() });
	try {
		const patched = await api.post(`/api/v1/chats/${id}/history`, {
			headers: { authorization: `Bearer ${token}` },
			data: { upsert: { 'assistant-1': { content } } }
		});
		if (!patched.ok()) {
			throw new Error(`patch chat failed: ${patched.status()} ${await patched.text()}`);
		}
	} finally {
		await api.dispose();
	}
}
