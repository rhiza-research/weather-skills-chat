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

export const getTeams = async (token: string) => request(token, '/teams/');

export const getTeamById = async (token: string, id: string) => request(token, `/teams/${id}`);

export const createTeam = async (token: string, team: { name: string; description?: string }) =>
	request(token, '/teams/', { method: 'POST', body: JSON.stringify(team) });

export const updateTeamById = async (
	token: string,
	id: string,
	team: { name?: string; description?: string }
) => request(token, `/teams/${id}/update`, { method: 'POST', body: JSON.stringify(team) });

export const addTeamMember = async (
	token: string,
	id: string,
	userId: string,
	role: string = 'member'
) =>
	request(token, `/teams/${id}/members`, {
		method: 'POST',
		body: JSON.stringify({ user_id: userId, role })
	});

export const updateTeamMemberRole = async (
	token: string,
	id: string,
	userId: string,
	role: string
) =>
	request(token, `/teams/${id}/members/${userId}`, {
		method: 'POST',
		body: JSON.stringify({ role })
	});

export const removeTeamMember = async (token: string, id: string, userId: string) =>
	request(token, `/teams/${id}/members/${userId}`, { method: 'DELETE' });

export const deleteTeamById = async (token: string, id: string) =>
	request(token, `/teams/${id}`, { method: 'DELETE' });
