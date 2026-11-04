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

export const getAutomations = async (token: string) => request(token, '/automations/');

export const getRunnerSizes = async (token: string, organizationId?: string | null) =>
	request(
		token,
		`/automations/runner-sizes${organizationId ? `?organization_id=${encodeURIComponent(organizationId)}` : ''}`
	);

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

export const setAutomationPinned = async (token: string, id: string, pinned: boolean) =>
	request(token, `/automations/${id}/pin`, { method: 'POST', body: JSON.stringify({ pinned }) });

export const markAutomationRunSeen = async (token: string, id: string, runId: string) =>
	request(token, `/automations/${id}/seen`, {
		method: 'POST',
		body: JSON.stringify({ run_id: runId })
	});

/** The task's picture. `version` is its image_updated_at, so a new picture is a new URL. */
export const getAutomationImageUrl = (id: string, version: number) =>
	`${WEBUI_API_BASE_URL}/automations/${id}/image?v=${version}`;

export const deleteAutomationImage = async (token: string, id: string) =>
	request(token, `/automations/${id}/image`, { method: 'DELETE' });

/** The cron a schedule phrase would save as, or null when it is not understood. */
export const previewSchedule = async (token: string, schedule: string) =>
	request(token, '/automations/schedule', {
		method: 'POST',
		body: JSON.stringify({ schedule })
	});
