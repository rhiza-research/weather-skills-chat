import { WEBUI_API_BASE_URL } from '$lib/constants';
import { parseApiError } from '$lib/apis/response';

const request = async (path: string, token: string, options: RequestInit = {}) => {
	const res = await fetch(`${WEBUI_API_BASE_URL}${path}`, {
		...options,
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			...(token ? { Authorization: `Bearer ${token}` } : {}),
			...(options.headers || {})
		}
	});
	if (!res.ok) {
		const error = await parseApiError(res);
		throw error.detail || error;
	}
	return res.json();
};

export const getPlatformInvitations = (token: string) =>
	request('/users/invitations', token);

export const createPlatformInvitation = (
	token: string,
	email: string,
	monthlyLimitUsd: number | null = 300
) =>
	request('/users/invitations', token, {
		method: 'POST',
		body: JSON.stringify({ email, monthly_limit_usd: monthlyLimitUsd })
	});

export const resendPlatformInvitation = (token: string, id: string) =>
	request(`/users/invitations/${id}/resend`, token, { method: 'POST' });

export const cancelPlatformInvitation = (token: string, id: string) =>
	request(`/users/invitations/${id}`, token, { method: 'DELETE' });

export const getOrganizationInvitations = (token: string, organizationId: string) =>
	request(`/organizations/${organizationId}/invitations`, token);

export const createOrganizationInvitation = (
	token: string,
	organizationId: string,
	email: string,
	monthlyLimitUsd: number | null = null
) =>
	request(`/organizations/${organizationId}/invitations`, token, {
		method: 'POST',
		body: JSON.stringify({ email, monthly_limit_usd: monthlyLimitUsd })
	});

export const resendOrganizationInvitation = (
	token: string,
	organizationId: string,
	id: string
) =>
	request(`/organizations/${organizationId}/invitations/${id}/resend`, token, {
		method: 'POST'
	});

export const cancelOrganizationInvitation = (
	token: string,
	organizationId: string,
	id: string
) =>
	request(`/organizations/${organizationId}/invitations/${id}`, token, {
		method: 'DELETE'
	});

export const getInvitation = (tokenValue: string) =>
	request(`/invitations/${encodeURIComponent(tokenValue)}`, '');

export const acceptInvitation = (
	tokenValue: string,
	sessionToken: string,
	body: { name?: string; password?: string } = {}
) =>
	request(`/invitations/${encodeURIComponent(tokenValue)}/accept`, sessionToken, {
		method: 'POST',
		credentials: sessionToken ? 'include' : 'omit',
		body: JSON.stringify(body)
	});
