import { expect, test } from 'vitest';
import { accumulateUsage } from './usage';

test('first usage is copied', () => {
	const incoming = { prompt_tokens: 10, completion_tokens: 4, total_tokens: 14, cost: 0.001 };
	expect(accumulateUsage(undefined, incoming)).toEqual(incoming);
	expect(accumulateUsage(undefined, incoming)).not.toBe(incoming);
});

test('sums token and cost fields across turns', () => {
	const first = {
		prompt_tokens: 100,
		completion_tokens: 20,
		total_tokens: 120,
		cost: 0.01,
		is_byok: false,
		prompt_tokens_details: { cached_tokens: 8 },
		cost_details: { upstream_inference_cost: 0.009 }
	};
	const second = {
		prompt_tokens: 40,
		completion_tokens: 15,
		total_tokens: 55,
		cost: 0.004,
		is_byok: true,
		prompt_tokens_details: { cached_tokens: 2 },
		cost_details: { upstream_inference_cost: 0.003 }
	};
	expect(accumulateUsage(first, second)).toEqual({
		prompt_tokens: 140,
		completion_tokens: 35,
		total_tokens: 175,
		cost: 0.014,
		is_byok: true,
		prompt_tokens_details: { cached_tokens: 10 },
		cost_details: { upstream_inference_cost: 0.012 }
	});
});

test('does not mutate inputs', () => {
	const existing = { prompt_tokens: 1, cost_details: { upstream_inference_cost: 0.1 } };
	const incoming = { prompt_tokens: 2, cost_details: { upstream_inference_cost: 0.2 } };
	accumulateUsage(existing, incoming);
	expect(existing).toEqual({ prompt_tokens: 1, cost_details: { upstream_inference_cost: 0.1 } });
	expect(incoming).toEqual({ prompt_tokens: 2, cost_details: { upstream_inference_cost: 0.2 } });
});

test('ignores non-token non-cost numbers', () => {
	expect(
		accumulateUsage({ prompt_tokens: 1, latency_ms: 10 }, { prompt_tokens: 2, latency_ms: 99 })
	).toEqual({ prompt_tokens: 3, latency_ms: 99 });
});
