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

async function chatRevision(api: Awaited<ReturnType<typeof playwrightRequest.newContext>>, token: string, id: string) {
	const got = await api.get(`/api/v1/chats/${id}`, {
		headers: { authorization: `Bearer ${token}` }
	});
	if (!got.ok()) {
		throw new Error(`get chat failed: ${got.status()} ${await got.text()}`);
	}
	const body = (await got.json()) as { meta?: { revision?: number } };
	return Number(body?.meta?.revision ?? 0);
}

/** The same completion request a focused tab sends. */
export async function sendTurn(token: string, id: string, content: string) {
	await ensureChatModel(token);
	const api = await playwrightRequest.newContext({ baseURL: apiOrigin() });
	const userId = `user-${Date.now()}`;
	const assistantId = `assistant-${Date.now()}`;
	try {
		const expectedRevision = await chatRevision(api, token, id);
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
					expected_revision: expectedRevision,
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

/** A send that must 409 because the client is carrying a stale revision. */
export async function sendTurnAtRevision(
	token: string,
	id: string,
	content: string,
	expectedRevision: number
) {
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
					expected_revision: expectedRevision,
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
		return { status: sent.status(), body: await sent.text() };
	} finally {
		await api.dispose();
	}
}

const fixturesOff =
	'ENABLE_E2E_FIXTURES is not true on the app under test. Set it on the server (CI Docker, local Docker, or uvicorn). Playwright does not need it.';

/** Keep the first-page sidebar list small so aged chats stay visible. */
export async function clearChats() {
	const { api, token } = await authed();
	try {
		const cleared = await api.post('/api/v1/chats/e2e/clear', {
			headers: { authorization: `Bearer ${token}` }
		});
		if (cleared.status() === 404) throw new Error(fixturesOff);
		if (!cleared.ok()) {
			throw new Error(`clear chats failed: ${cleared.status()} ${await cleared.text()}`);
		}
	} finally {
		await api.dispose();
	}
}

/** Move a chat onto a past calendar day so the sidebar lists it under an older range. */
export async function ageChat(token: string, id: string, daysAgo: number) {
	const api = await playwrightRequest.newContext({ baseURL: apiOrigin() });
	try {
		const aged = await api.post(`/api/v1/chats/${id}/e2e/age`, {
			headers: { authorization: `Bearer ${token}` },
			data: { days_ago: daysAgo }
		});
		if (aged.status() === 404) throw new Error(fixturesOff);
		if (!aged.ok()) {
			throw new Error(`age chat failed: ${aged.status()} ${await aged.text()}`);
		}
		const stamped = (await aged.json()) as { updated_at: number };
		const got = await api.get(`/api/v1/chats/${id}`, {
			headers: { authorization: `Bearer ${token}` }
		});
		if (!got.ok()) {
			throw new Error(`get chat failed: ${got.status()} ${await got.text()}`);
		}
		const row = (await got.json()) as { updated_at: number };
		if (Math.abs(row.updated_at - stamped.updated_at) >= 2) {
			throw new Error(
				`chat ${id} did not stay aged (set ${stamped.updated_at}, got ${row.updated_at})`
			);
		}
	} finally {
		await api.dispose();
	}
}

/** Replace the assistant message. This commits the chat and emits chat:updated. */
export async function replaceAssistant(token: string, id: string, content: string) {
	const api = await playwrightRequest.newContext({ baseURL: apiOrigin() });
	try {
		const expectedRevision = await chatRevision(api, token, id);
		const patched = await api.post(`/api/v1/chats/${id}/history`, {
			headers: { authorization: `Bearer ${token}` },
			data: {
				upsert: { 'assistant-1': { content } },
				expected_revision: expectedRevision
			}
		});
		if (!patched.ok()) {
			throw new Error(`patch chat failed: ${patched.status()} ${await patched.text()}`);
		}
	} finally {
		await api.dispose();
	}
}
