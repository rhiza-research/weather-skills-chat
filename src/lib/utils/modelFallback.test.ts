import { describe, expect, it } from 'vitest';
import {
	bareModelName,
	fallbackOptions,
	matchesSearch,
	modelSelectItems,
	providerModelLabel,
	suggestFallback,
	type ListedModel
} from './modelFallback';

const openrouter = (id: string): ListedModel => ({
	id,
	urlIdx: 0,
	connection_name: 'openrouter.ai',
	upstream_id: id
});

const requesty = (id: string): ListedModel => ({
	id: `requesty.${id}`,
	urlIdx: 1,
	connection_name: 'requesty',
	upstream_id: id
});

const models = [
	openrouter('anthropic/claude-sonnet-4.5'),
	openrouter('openai/gpt-5'),
	requesty('bedrock/claude-sonnet-4-5'),
	requesty('anthropic/claude-sonnet-4-5-20250929'),
	requesty('openai/gpt-5'),
	{ id: 'weather-pipe', name: 'Weather pipe' }
];

describe('providerModelLabel', () => {
	it('names the connection and the id it sends', () => {
		expect(providerModelLabel(requesty('openai/gpt-5'))).toBe('requesty/openai/gpt-5');
	});

	it('uses the name for a model without a connection', () => {
		expect(providerModelLabel({ id: 'weather-pipe', name: 'Weather pipe' })).toBe('Weather pipe');
	});
});

describe('bareModelName', () => {
	it('drops the vendor, version dots, date and variant', () => {
		expect(bareModelName('anthropic/claude-sonnet-4.5')).toBe('claude-sonnet-4-5');
		expect(bareModelName('anthropic/claude-sonnet-4-5-20250929')).toBe('claude-sonnet-4-5');
		expect(bareModelName('meta-llama/llama-3.3-70b:free')).toBe('llama-3-3-70b');
	});
});

describe('fallbackOptions', () => {
	it('lists only models from other connections', () => {
		const ids = fallbackOptions(models, 'anthropic/claude-sonnet-4.5').map((m) => m.id);
		expect(ids).toEqual([
			'requesty.bedrock/claude-sonnet-4-5',
			'requesty.anthropic/claude-sonnet-4-5-20250929',
			'requesty.openai/gpt-5'
		]);
	});

	it('is empty without a base model from a connection', () => {
		expect(fallbackOptions(models, null)).toEqual([]);
		expect(fallbackOptions(models, 'weather-pipe')).toEqual([]);
	});
});

describe('suggestFallback', () => {
	it('picks the same model on another connection, preferring the same vendor', () => {
		expect(suggestFallback(models, 'anthropic/claude-sonnet-4.5')).toBe(
			'requesty.anthropic/claude-sonnet-4-5-20250929'
		);
		expect(suggestFallback(models, 'openai/gpt-5')).toBe('requesty.openai/gpt-5');
	});

	it('suggests nothing when no other connection has the model', () => {
		expect(suggestFallback([openrouter('openai/gpt-5')], 'openai/gpt-5')).toBeNull();
		expect(suggestFallback(models, 'weather-pipe')).toBeNull();
	});
});

describe('modelSelectItems', () => {
	it('labels models by connection and sorts them alphabetically', () => {
		expect(modelSelectItems(models).map((item) => item.label)).toEqual([
			'openrouter.ai/anthropic/claude-sonnet-4.5',
			'openrouter.ai/openai/gpt-5',
			'requesty/anthropic/claude-sonnet-4-5-20250929',
			'requesty/bedrock/claude-sonnet-4-5',
			'requesty/openai/gpt-5',
			'Weather pipe'
		]);
	});
});

describe('matchesSearch', () => {
	it('matches every typed word anywhere in the label, ignoring case', () => {
		expect(matchesSearch('requesty/anthropic/claude-sonnet-4-5', 'Sonnet req')).toBe(true);
		expect(matchesSearch('requesty/anthropic/claude-sonnet-4-5', 'sonnet openrouter')).toBe(false);
		expect(matchesSearch('openrouter.ai/openai/gpt-5', '  ')).toBe(true);
	});
});
