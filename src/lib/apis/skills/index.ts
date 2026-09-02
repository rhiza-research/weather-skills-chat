import { WEBUI_API_BASE_URL } from '$lib/constants';
import { parseApiError } from '$lib/apis/response';

const authHeaders = (token: string) => ({
	Accept: 'application/json',
	'Content-Type': 'application/json',
	authorization: `Bearer ${token}`
});

export const getSkillPacks = async (token: string = '') => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/skills/`, {
		method: 'GET',
		headers: authHeaders(token)
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
	if (error) throw error;
	return res;
};

export const installSkillPack = async (
	token: string,
	gitUrl: string,
	ref: string = 'main'
) => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/skills/install`, {
		method: 'POST',
		headers: authHeaders(token),
		body: JSON.stringify({ git_url: gitUrl, ref: ref || 'main' })
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
	if (error) throw error;
	return res;
};

export const updateSkillPack = async (
	token: string,
	packId: string,
	ref: string | null = null
) => {
	let error = null;
	const body: Record<string, string> = {};
	if (ref) body.ref = ref;
	const res = await fetch(`${WEBUI_API_BASE_URL}/skills/${packId}/update`, {
		method: 'POST',
		headers: authHeaders(token),
		body: JSON.stringify(body)
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
	if (error) throw error;
	return res;
};

export const deleteSkillPack = async (token: string, packId: string) => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/skills/${packId}`, {
		method: 'DELETE',
		headers: authHeaders(token)
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
	if (error) throw error;
	return res;
};

export const updateSkillPackAccess = async (
	token: string,
	packId: string,
	accessControl: object | null
) => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/skills/${packId}/access`, {
		method: 'POST',
		headers: authHeaders(token),
		body: JSON.stringify({ access_control: accessControl })
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
	if (error) throw error;
	return res;
};

export const updateSkillEnabled = async (
	token: string,
	packId: string,
	toolId: string,
	enabled: boolean
) => {
	let error = null;
	const res = await fetch(
		`${WEBUI_API_BASE_URL}/skills/${packId}/skills/${encodeURIComponent(toolId)}/enabled`,
		{
			method: 'POST',
			headers: authHeaders(token),
			body: JSON.stringify({ enabled })
		}
	)
		.then(async (res) => {
			if (!res.ok) throw await parseApiError(res);
			return res.json();
		})
		.catch((err) => {
			error = err.detail ?? err;
			console.log(err);
			return null;
		});
	if (error) throw error;
	return res;
};
