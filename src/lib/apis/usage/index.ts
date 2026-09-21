import { WEBUI_API_BASE_URL } from '$lib/constants';
import { parseApiError } from '$lib/apis/response';
import { organizationHeaders } from '$lib/apis/organizations';

export type UsageTotals = {
	organization_id?: string;
	user_id?: string;
	period: string;
	prompt_tokens: number;
	completion_tokens: number;
	total_tokens: number;
	cached_tokens: number;
	uncached_tokens: number;
	cost_usd: number;
};

export type UsageMe = UsageTotals & {
	organization_id: string;
	organization_name: string;
	org_cost_usd: number;
	org_limit_usd: number | null;
	user_limit_usd: number | null;
	effective_limit_usd: number | null;
	remaining_usd: number | null;
	over_limit: boolean;
	message: string | null;
};

export const getMyUsage = async (token: string): Promise<UsageMe> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/usage/me`, {
		headers: {
			Accept: 'application/json',
			authorization: `Bearer ${token}`,
			...organizationHeaders()
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await parseApiError(res);
			return res.json();
		})
		.catch((err) => {
			error = err.detail ?? err;
			return null;
		});

	if (error) {
		throw error;
	}
	return res;
};
