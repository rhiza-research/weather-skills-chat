import { describe, expect, it } from 'vitest';
import {
	MAX_NODES,
	argRows,
	buildGraph,
	columns,
	layoutGraph,
	nodeKind,
	viewGraph
} from './provenanceGraph';

const step = (skill: string, args: object = {}, input: unknown = null) => ({
	skill,
	version: '1.0',
	args,
	input
});
const ref = (basename: string, history?: unknown[]) => ({
	basename,
	hash: 'h',
	history
});
const width = (s: string) => s.length * 6;

// Oldest first; each step after the first reads the one before it.
const chain = (...skills: string[]) =>
	skills.map((s, i) => step(s, {}, i ? ref(`${i}.zarr`) : null));

describe('buildGraph', () => {
	it('turns a chain into a path ending in the file', () => {
		const { graph } = buildGraph(
			[{ steps: chain('chirps-fetch', 'clip-region', 'plot') }],
			'a.png'
		);
		const N = graph!.nodes;
		expect(N.f).toMatchObject({ label: 'a.png', file: true });
		const labels = (id: string): string[] => [N[id].label, ...N[id].in.flatMap(labels)];
		expect(labels('f')).toEqual(['a.png', 'plot', 'clip-region', 'chirps-fetch']);
		expect(nodeKind(N[N[N.f.in[0]].in[0]])).toBe('step');
	});

	it('joins input histories and merges a shared upstream into one node', () => {
		const clim = chain('chirps-fetch', 'reduce');
		const fc = chain('ecmwf-fetch', 'deaccumulate');
		const obs = chain('imerg-fetch', 'clip-region');
		const steps = [
			step('plot-compare', {}, [
				ref('a.zarr', [step('difference', {}, [ref('f.zarr', fc), ref('c.zarr', clim)])]),
				ref('b.zarr', [step('difference', {}, [ref('o.zarr', obs), ref('c.zarr', clim)])])
			])
		];
		const { graph } = buildGraph([{ steps }], 'cmp.png');
		const N = graph!.nodes;
		const reduces = Object.values(N).filter((n) => n.label === 'reduce');
		expect(reduces).toHaveLength(1);
		const diffs = Object.values(N).filter((n) => n.label === 'difference');
		expect(diffs.map((d) => nodeKind(d))).toEqual(['combine', 'combine']);
		expect(nodeKind(Object.values(N).find((n) => n.label === 'plot-compare')!)).toBe('plot');
	});

	it('gives every node a generated id and keeps hostile text as plain labels', () => {
		const evil = '<img src=x onerror=alert(1)>';
		const { graph } = buildGraph(
			[
				{
					steps: [
						step(evil, { ['__proto__']: evil, constructor: '"><script>' }),
						step('x"]', {}, ref('a'))
					]
				}
			],
			'"><svg onload=alert(1)>.png'
		);
		const N = graph!.nodes;
		for (const id of Object.keys(N)) expect(id).toMatch(/^(n\d+|f)$/);
		expect(Object.values(N).map((n) => n.label)).toContain(evil);
		expect(({} as any).polluted).toBeUndefined();
		const rows = argRows(Object.values(N).find((n) => n.label === evil)!.step!.args);
		expect(rows.map((r) => r.key).sort()).toEqual(['__proto__', 'constructor'].sort());
	});

	it('clips long labels but keeps the step for the popover', () => {
		const long = 'x'.repeat(500);
		const { graph } = buildGraph([{ steps: [step(long)] }], 'f');
		const n = Object.values(graph!.nodes).find((n) => n.step)!;
		expect(n.label.length).toBe(40);
		expect(n.step!.skill).toBe(long);
	});

	it('refuses graphs that are too large or too deep instead of hanging', () => {
		const wide = Array.from({ length: MAX_NODES + 5 }, (_, i) =>
			step(`s${i}`, {}, i ? ref('p') : null)
		);
		expect(buildGraph([{ steps: wide }], 'f')).toEqual({
			graph: null,
			tooBig: true
		});
		let deep: unknown[] = [step('fetch')];
		for (let i = 0; i < 100; i++) deep = [step(`s${i}`, {}, ref('p', deep))];
		expect(buildGraph([{ steps: deep }], 'f').tooBig).toBe(true);
	});

	it('drops steps the file does not depend on, which dagre cannot lay out', () => {
		// A join reads only its inputs' histories, so the step before it leads nowhere.
		const c = [step('fetch', { y: 1 }), step('clip', {}, ref('1.zarr'))];
		const steps = [
			step('fetch', { a: 1 }),
			step('orphan', {}, ref('x')),
			step('plot', {}, [ref('o', c)])
		];
		const g = buildGraph([{ steps }], 'e.png').graph!;
		expect(Object.values(g.nodes).map((n) => n.label)).not.toContain('orphan');
		for (const k of [5, 6.3, 7])
			expect(() => layoutGraph(viewGraph(g, new Set()), (s) => s.length * k)).not.toThrow();
	});

	it('leaves arguments that were not set out of the popover rows', () => {
		const rows = argRows({ cmap: 'BrBG', norm: null, vmin: 0, flag: false, title: '', gone: undefined });
		expect(rows.map((r) => r.key)).toEqual(['cmap', 'vmin', 'flag', 'title']);
		expect(argRows({ norm: null })).toEqual([]);
	});

	it('ignores malformed entries', () => {
		expect(buildGraph([{ steps: [null, 3, { skill: 5 }, 'x'] }], 'f').graph).toBeNull();
		expect(buildGraph(null, 'f').graph).toBeNull();
		expect(buildGraph([{ steps: 'nope' }], 'f').graph).toBeNull();
	});
});

describe('viewGraph and layout', () => {
	const g = buildGraph(
		[
			{
				steps: chain('chirps-fetch', 'clip-region', 'aggregate-temporal', 'coarsen', 'plot')
			}
		],
		'p.png'
	).graph!;

	it('collapses a straight run and expands it behind a handle', () => {
		const closed = viewGraph(g, new Set());
		expect(closed.heads).toHaveLength(1);
		const run = Object.values(closed.nodes).find((n) => n.run)!;
		expect(run.label).toBe('+ 3 steps');
		const opened = viewGraph(g, new Set(closed.heads));
		expect(Object.values(opened.nodes).some((n) => n.run)).toBe(false);
		expect(Object.values(opened.nodes).find((n) => n.handle)!.count).toBe(3);
		expect(opened.bands).toHaveLength(1);
	});

	it('puts every source in the first column', () => {
		const two = buildGraph(
			[
				{
					steps: [
						step('difference', {}, [
							ref('a', chain('ecmwf-fetch', 'deaccumulate', 'reduce')),
							ref('b', chain('chirps-fetch'))
						])
					]
				}
			],
			'd.png'
		).graph!;
		const col = columns(two);
		for (const [id, n] of Object.entries(two.nodes)) if (!n.in.length) expect(col[id]).toBe(0);
	});

	it('lays out with numbers only', () => {
		const L = layoutGraph(viewGraph(g, new Set()), width);
		expect(L.W).toBeGreaterThan(0);
		expect(L.H).toBeGreaterThan(0);
		for (const n of L.nodes)
			for (const v of [n.x, n.y, n.w, n.h]) expect(Number.isFinite(v)).toBe(true);
		for (const e of L.edges) expect(e.d).toMatch(/^[MLCZ0-9.,\-e ]+$/);
	});
});
