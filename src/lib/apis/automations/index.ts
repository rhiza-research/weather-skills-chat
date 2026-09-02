import { WEBUI_API_BASE_URL } from '$lib/constants';
import { parseApiError } from '$lib/apis/response';

const request = async (token: string, path: string, options: RequestInit = {}) => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}${path}`, {
		...options,
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`,
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

export const getAutomations = async (token: string) => request(token, '/automations/');

export const getAutomationById = async (token: string, id: string) =>
	request(token, `/automations/${id}`);

export const createAutomation = async (token: string, automation: object) =>
	request(token, '/automations/', { method: 'POST', body: JSON.stringify(automation) });

export const updateAutomationById = async (token: string, id: string, automation: object) =>
	request(token, `/automations/${id}/update`, {
		method: 'POST',
		body: JSON.stringify(automation)
	});

export const deleteAutomationById = async (token: string, id: string) =>
	request(token, `/automations/${id}`, { method: 'DELETE' });

export const runAutomationById = async (token: string, id: string) =>
	request(token, `/automations/${id}/run`, { method: 'POST' });

export const getAutomationRuns = async (token: string, id: string) =>
	request(token, `/automations/${id}/runs`);
