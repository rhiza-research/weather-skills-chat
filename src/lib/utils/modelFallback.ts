/** Labels and the name match for a model's backup in the model editor. */

export type ListedModel = {
	id: string;
	name?: string;
	urlIdx?: number;
	// Set by the backend for models from an OpenAI-compatible connection.
	connection_name?: string;
	upstream_id?: string;
};

/** `connection/model-id` for a model from a connection, else its name. */
export const providerModelLabel = (model: ListedModel): string =>
	model.connection_name
		? `${model.connection_name}/${model.upstream_id ?? model.id}`
		: (model.name ?? model.id);

const upstreamId = (model: ListedModel): string => model.upstream_id ?? model.id;

/** The model's name without its vendor, version punctuation, date or variant. */
export const bareModelName = (id: string): string =>
	(id.split('/').pop() ?? id)
		.toLowerCase()
		.replace(/:.*$/, '')
		.replace(/\./g, '-')
		.replace(/-\d{8}$/, '');

const vendor = (id: string): string | null => (id.includes('/') ? id.split('/')[0] : null);

/** Models from a different connection than `baseId`'s, which can back it up. */
export const fallbackOptions = (models: ListedModel[], baseId: string | null): ListedModel[] => {
	const base = models.find((m) => m.id === baseId);
	if (base?.urlIdx === undefined) {
		return [];
	}
	return models.filter((m) => m.connection_name && m.urlIdx !== base.urlIdx);
};

/**
 * The backup with the same model name as `baseId`, preferring the same
 * vendor, or null when no other connection has it.
 */
export const suggestFallback = (models: ListedModel[], baseId: string | null): string | null => {
	const base = models.find((m) => m.id === baseId);
	if (!base) {
		return null;
	}
	const name = bareModelName(upstreamId(base));
	const matches = fallbackOptions(models, baseId).filter(
		(m) => bareModelName(upstreamId(m)) === name
	);
	const baseVendor = vendor(upstreamId(base));
	const sameVendor = matches.find((m) => vendor(upstreamId(m)) === baseVendor);
	return (sameVendor ?? matches[0])?.id ?? null;
};

export type SelectItem = { value: string | null; label: string };

/** Select items for `models`, labelled `connection/model-id` and sorted by label. */
export const modelSelectItems = (models: ListedModel[]): SelectItem[] =>
	models
		.map((m) => ({ value: m.id, label: providerModelLabel(m) }))
		.sort((a, b) => a.label.localeCompare(b.label, undefined, { sensitivity: 'base' }));

/** Whether every word typed appears in `label`, ignoring case. */
export const matchesSearch = (label: string, query: string): boolean => {
	const text = label.toLowerCase();
	return query
		.toLowerCase()
		.split(/\s+/)
		.filter(Boolean)
		.every((word) => text.includes(word));
};
