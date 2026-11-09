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

// Brackets whose text is at most this long stay on one line.
const INLINE_MAX = 60;

/**
 * Re-indent Jsonnet written on one line: each `local ...;` on its own line, and
 * objects and arrays one entry per line unless short. Strings are left untouched.
 */
export function formatJsonnet(src: string): string {
	const toks: string[] = [];
	for (let i = 0; i < src.length; ) {
		const ch = src[i];
		if (ch === '"' || ch === "'") {
			let j = i + 1;
			while (j < src.length && src[j] !== ch) j += src[j] === '\\' ? 2 : 1;
			toks.push(src.slice(i, j + 1));
			i = j + 1;
		} else if (/\s/.test(ch)) {
			if (toks[toks.length - 1] !== ' ') toks.push(' ');
			i++;
		} else {
			toks.push(ch);
			i++;
		}
	}

	const closeOf = (k: number) => {
		for (let depth = 0, j = k; j < toks.length; j++) {
			if (toks[j] === '{' || toks[j] === '[') depth++;
			else if ((toks[j] === '}' || toks[j] === ']') && --depth === 0) return j;
		}
		return -1;
	};

	let out = '';
	const stack: string[] = [];
	const newline = () => {
		out = out.trimEnd() + '\n' + '  '.repeat(stack.filter((s) => s !== '(').length);
	};
	for (let k = 0; k < toks.length; k++) {
		const t = toks[k];
		if (t === '{' || t === '[') {
			const close = closeOf(k);
			const inline = close < 0 ? '' : toks.slice(k, close + 1).join('');
			if (inline && inline.length <= INLINE_MAX) {
				out += inline;
				k = close;
			} else {
				stack.push(t);
				out += t;
				newline();
			}
		} else if (t === '}' || t === ']') {
			stack.pop();
			newline();
			out += t;
		} else if (t === '(' || t === ')') {
			if (t === '(') stack.push(t);
			else stack.pop();
			out += t;
		} else if (t === ',' && stack.length && stack[stack.length - 1] !== '(') {
			out += t;
			newline();
		} else if (t === ';') {
			out += t;
			newline();
		} else if (t === ' ') {
			if (!/\s$/.test(out) && out) out += t;
		} else {
			out += t;
		}
	}
	return out.trim();
}

/**
 * Pretty-print strings that are a JSON object or array, and re-indent one-line
 * Jsonnet; leave other strings as written.
 */
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
				// Not JSON: maybe Jsonnet, below.
			}
		}
		// Multi-line Jsonnet keeps its author's layout; only one-liners are re-indented.
		if (!value.includes('\n') && /^(local\s|\{|\[)/.test(trimmed)) {
			return { text: formatJsonnet(trimmed), lang: '' };
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
