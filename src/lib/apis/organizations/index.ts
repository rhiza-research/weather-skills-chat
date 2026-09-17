import { WEBUI_API_BASE_URL } from '$lib/constants';
import { parseApiError } from '$lib/apis/response';
import { get } from 'svelte/store';
import { activeOrganizationId } from '$lib/stores';

export const organizationHeaders = (): Record<string, string> => {
	const id = get(activeOrganizationId);
	return id ? { 'X-Organization-Id': id } : {};
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

export const updateOrganizationById = async (
	token: string,
	id: string,
	org: { name?: string; description?: string; default_models?: string | null }
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

export const removeOrganizationMember = async (token: string, id: string, userId: string) =>
	request(token, `/organizations/${id}/members/${userId}`, { method: 'DELETE' });

export const deleteOrganizationById = async (token: string, id: string) =>
	request(token, `/organizations/${id}`, { method: 'DELETE' });
