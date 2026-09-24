import { WEBUI_API_BASE_URL, WEBUI_BASE_URL } from '$lib/constants';
import { parseApiError } from '$lib/apis/response';
import { get } from 'svelte/store';
import { activeOrganizationId } from '$lib/stores';
import { PLATFORM_ORG_ID } from '$lib/utils/catalog';

export { PLATFORM_ORG_ID };

export const organizationHeaders = (): Record<string, string> => {
	const id = get(activeOrganizationId);
	return id ? { 'X-Organization-Id': id } : {};
};

let fetchPatched = false;

export const installOrganizationFetch = () => {
	if (typeof window === 'undefined' || fetchPatched) {
		return;
	}
	fetchPatched = true;
	if (typeof localStorage !== 'undefined') {
		const stored = localStorage.getItem('activeOrganizationId');
		if (stored && !get(activeOrganizationId)) {
			activeOrganizationId.set(stored);
		}
	}
	const originalFetch = window.fetch.bind(window);
	window.fetch = (input, init) => {
		const orgId = get(activeOrganizationId);
		if (!orgId) {
			return originalFetch(input, init);
		}
		const url =
			typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
		const local =
			url.startsWith('/') ||
			url.startsWith(WEBUI_API_BASE_URL) ||
			(WEBUI_BASE_URL && url.startsWith(WEBUI_BASE_URL));
		if (!local) {
			return originalFetch(input, init);
		}
		if (typeof Request !== 'undefined' && input instanceof Request) {
			if (!input.headers.has('X-Organization-Id')) {
				const headers = new Headers(input.headers);
				headers.set('X-Organization-Id', orgId);
				input = new Request(input, { headers });
			}
			return originalFetch(input, init);
		}
		const headers = new Headers(init?.headers);
		if (!headers.has('X-Organization-Id')) {
			headers.set('X-Organization-Id', orgId);
		}
		return originalFetch(input, { ...(init || {}), headers });
	};
};

const request = async (token: string, path: string, options: RequestInit = {}) => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}${path}`, {
		...options,
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`,
			...organizationHeaders(),
			...(options.headers || {})
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await parseApiError(res);
			return res.json();
		})
		.catch((err) => {
			error = err.detail ?? err;
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}
	return res;
};

export const getOrganizations = async (token: string) => request(token, '/organizations/');

export const getAllOrganizations = async (token: string) => request(token, '/organizations/all');

export const getOrganizationById = async (token: string, id: string) =>
	request(token, `/organizations/${id}`);

export const createOrganization = async (
	token: string,
	org: { name: string; description?: string; default_models?: string | null }
) => request(token, '/organizations/', { method: 'POST', body: JSON.stringify(org) });

export const activateOrganization = async (token: string, id: string) =>
	request(token, `/organizations/${id}/activate`, { method: 'POST' });

export const updateOrganizationById = async (
	token: string,
	id: string,
	org: {
		name?: string;
		description?: string;
		default_models?: string | null;
		can_add_models?: boolean;
		can_add_skills?: boolean;
		can_add_knowledge?: boolean;
		monthly_limit_usd?: number | null;
		logo?: string | null;
	}
) =>
	request(token, `/organizations/${id}/update`, {
		method: 'POST',
		body: JSON.stringify(org)
	});

export const addOrganizationMember = async (
	token: string,
	id: string,
	userId: string,
	role: string = 'user'
) =>
	request(token, `/organizations/${id}/members`, {
		method: 'POST',
		body: JSON.stringify({ user_id: userId, role })
	});

export const updateOrganizationMemberRole = async (
	token: string,
	id: string,
	userId: string,
	role: string
) =>
	request(token, `/organizations/${id}/members/${userId}`, {
		method: 'POST',
		body: JSON.stringify({ role })
	});

export const updateOrganizationMemberLimit = async (
	token: string,
	id: string,
	userId: string,
	monthlyLimitUsd: number | null
) =>
	request(token, `/organizations/${id}/members/${userId}/usage-limit`, {
		method: 'POST',
		body: JSON.stringify({ monthly_limit_usd: monthlyLimitUsd })
	});

export const removeOrganizationMember = async (token: string, id: string, userId: string) =>
	request(token, `/organizations/${id}/members/${userId}`, { method: 'DELETE' });

export const deleteOrganizationById = async (token: string, id: string) =>
	request(token, `/organizations/${id}`, { method: 'DELETE' });
