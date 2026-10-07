import type { createLowlight } from 'lowlight';

type Lowlight = ReturnType<typeof createLowlight>;

let real: Lowlight | null = null;
let pending: Promise<Lowlight> | null = null;

/** Fetch the highlighter grammars. Resolves once code blocks can be highlighted. */
export const loadLowlight = () =>
	(pending ??= import('./codeHighlight').then((module) => (real = module.lowlight)));

export const lowlightLoaded = () => real !== null;

const plain = (value: string) => ({
	type: 'root' as const,
	children: [{ type: 'text' as const, value }],
	data: { language: undefined, relevance: 0 }
});

/** Lowlight stand-in for the editor: plain text until the grammars arrive, then the real thing. */
export const lazyLowlight = {
	highlight: (language: string, value: string, options?: object) =>
		real ? real.highlight(language, value, options) : plain(value),
	highlightAuto: (value: string, options?: object) =>
		real ? real.highlightAuto(value, options) : plain(value),
	listLanguages: () => (real ? real.listLanguages() : []),
	registered: (name: string) => (real ? real.registered(name) : false)
} as unknown as Lowlight;
