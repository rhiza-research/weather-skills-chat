import hljs from 'highlight.js/lib/core';
import { createLowlight } from 'lowlight';
import type { LanguageFn } from 'highlight.js';

import bash from 'highlight.js/lib/languages/bash';
import css from 'highlight.js/lib/languages/css';
import javascript from 'highlight.js/lib/languages/javascript';
import json from 'highlight.js/lib/languages/json';
import markdown from 'highlight.js/lib/languages/markdown';
import python from 'highlight.js/lib/languages/python';
import r from 'highlight.js/lib/languages/r';
import sql from 'highlight.js/lib/languages/sql';
import typescript from 'highlight.js/lib/languages/typescript';
import xml from 'highlight.js/lib/languages/xml';
import yaml from 'highlight.js/lib/languages/yaml';

const grammars: Record<string, LanguageFn> = {
	python,
	javascript,
	typescript,
	json,
	bash,
	yaml,
	xml,
	css,
	markdown,
	sql,
	r
};

for (const [name, grammar] of Object.entries(grammars)) {
	hljs.registerLanguage(name, grammar);
}

export const lowlight = createLowlight(grammars);

const escapeHtml = (value: string) =>
	value.replace(/[&<>"']/g, (char) => {
		switch (char) {
			case '&':
				return '&amp;';
			case '<':
				return '&lt;';
			case '>':
				return '&gt;';
			case '"':
				return '&quot;';
			default:
				return '&#39;';
		}
	});

export const highlightCode = (code: string, lang: string) => {
	if (lang && hljs.getLanguage(lang)) {
		return hljs.highlight(code, { language: lang }).value;
	}
	return escapeHtml(code);
};
