import { WEBUI_API_BASE_URL } from '$lib/constants';

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
			if (!res.ok) throw await res.json();
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

export const getSecrets = async (token: string) => request(token, '/secrets/');

export const getTeamSecrets = async (token: string, teamId: string) =>
	request(token, `/secrets/team/${teamId}`);

export const createSecret = async (
	token: string,
	secret: { name: string; value: string; team_id?: string | null }
) => request(token, '/secrets/', { method: 'POST', body: JSON.stringify(secret) });

export const updateSecretById = async (
	token: string,
	id: string,
	secret: { name?: string; value?: string }
) =>
	request(token, `/secrets/${id}/update`, {
		method: 'POST',
		body: JSON.stringify(secret)
	});

export const deleteSecretById = async (token: string, id: string) =>
	request(token, `/secrets/${id}`, { method: 'DELETE' });
