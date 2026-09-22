import { WEBUI_API_BASE_URL } from '$lib/constants';
import { parseApiError } from '$lib/apis/response';
import { organizationHeaders } from '$lib/apis/organizations';

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

export const getPreferences = async (token: string) => request(token, '/preferences/');

export const createPreference = async (
	token: string,
	preference: {
		title: string;
		content: string;
		visibility?: string | null;
		enabled?: boolean;
	}
) => request(token, '/preferences/', { method: 'POST', body: JSON.stringify(preference) });

export const updatePreferenceById = async (
	token: string,
	id: string,
	preference: {
		title?: string;
		content?: string;
		visibility?: string | null;
		enabled?: boolean;
	}
) =>
	request(token, `/preferences/${id}/update`, {
		method: 'POST',
		body: JSON.stringify(preference)
	});

export const deletePreferenceById = async (token: string, id: string) =>
	request(token, `/preferences/${id}`, { method: 'DELETE' });
