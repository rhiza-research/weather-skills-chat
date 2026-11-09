/** Rows for the "Call" view of a tool call: one argument per row. */

export type ToolArgRow = {
	/** Argument name or CLI flag; empty for a positional value. */
	key: string;
	/** Value as display text, with real newlines. */
	value: string;
	/** 'json' when the value is pretty-printed JSON. */
	lang: '' | 'json';
	/** The value spans several lines and belongs in a code block. */
	multiline: boolean;
};

const isFlag = (value: unknown): value is string =>
	typeof value === 'string' && /^--?[A-Za-z]/.test(value);

/** Pretty-print strings that are a JSON object or array; leave other strings as written. */
export function formatToolArgValue(value: unknown): {
	text: string;
	lang: '' | 'json';
} {
	if (value === null || value === undefined) return { text: 'null', lang: '' };
	if (typeof value === 'string') {
		const trimmed = value.trim();
		if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
			try {
				const parsed = JSON.parse(trimmed);
				if (parsed && typeof parsed === 'object') {
					return { text: JSON.stringify(parsed, null, 2), lang: 'json' };
				}
			} catch {
				// Not JSON (e.g. Jsonnet): show the string with its own newlines.
			}
		}
		return { text: value === '' ? '""' : value, lang: '' };
	}
	if (typeof value === 'object') {
		try {
			return { text: JSON.stringify(value, null, 2), lang: 'json' };
		} catch {
			return { text: String(value), lang: '' };
		}
	}
	return { text: String(value), lang: '' };
}

const row = (key: string, value: unknown): ToolArgRow => {
	const { text, lang } = formatToolArgValue(value);
	return { key, value: text, lang, multiline: text.includes('\n') };
};

/** Pair CLI flags with the value after them: ["--spec", "{...}", "-o", "x.png"]. */
function argvRows(argv: unknown[]): ToolArgRow[] {
	const rows: ToolArgRow[] = [];
	for (let i = 0; i < argv.length; i++) {
		const item = argv[i];
		if (!isFlag(item)) {
			rows.push(row('', item));
			continue;
		}
		const eq = item.startsWith('--') ? item.indexOf('=') : -1;
		if (eq > 0) {
			rows.push(row(item.slice(0, eq), item.slice(eq + 1)));
		} else if (i + 1 < argv.length && !isFlag(argv[i + 1])) {
			rows.push(row(item, argv[++i]));
		} else {
			rows.push({ key: item, value: '', lang: '', multiline: false });
		}
	}
	return rows;
}

/** First line of the Call view: the tool name, plus the script for skill calls (`plot plot.py`). */
export function toolCallHead(name: string, args: unknown): string {
	const obj = args as Record<string, unknown> | null;
	const script = Array.isArray(obj?.argv) && typeof obj?.script === 'string' ? obj.script : '';
	return [name || 'tool', script].filter(Boolean).join(' ');
}

/**
 * Rows for parsed tool arguments. Skill calls ({argv, script}) list argv only, since
 * the script is on the head line; `display` is never shown.
 */
export function toolArgRows(args: unknown): ToolArgRow[] {
	if (Array.isArray(args)) return args.map((value) => row('', value));
	if (args && typeof args === 'object') {
		const obj = args as Record<string, unknown>;
		if (Array.isArray(obj.argv)) return argvRows(obj.argv);
		return Object.entries(obj)
			.filter(([key]) => key !== 'display')
			.map(([key, value]) => row(key, value));
	}
	if (args === null || args === undefined || args === '') return [];
	return [row('', args)];
}
