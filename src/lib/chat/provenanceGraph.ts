/**
 * Provenance as a DAG: the chains read from an artifact (weather_skills_history)
 * turned into nodes and edges, with straight runs collapsible, laid out left to
 * right by dagre. Provenance is read from files anyone can write, so nothing here
 * puts its text anywhere but node labels and arguments, which the components
 * render as text. Node ids are generated, never taken from the data.
 */
import { layout as dagreLayout } from 'dagre-d3-es/src/dagre/index.js';
import { Graph } from 'dagre-d3-es/src/graphlib/index.js';
import { line, curveBasis } from 'd3';
import { formatToolArgValue, type ToolArgRow } from './toolArgs';

export type ProvStep = {
	skill: string;
	version?: string;
	args?: unknown;
	input?: unknown;
};
export type ProvNode = {
	label: string;
	step?: ProvStep;
	file?: boolean;
	in: string[];
	/** Collapsed run: the ids of its steps, oldest first. */
	run?: string[];
	/** Handle before an expanded run: the run's first step. */
	handle?: string;
	count?: number;
};
export type ProvGraph = { nodes: Record<string, ProvNode>; sink: string };
export type ProvView = ProvGraph & { bands: string[][]; heads: string[] };

// Past these the graph is not drawn; the text view still shows everything.
export const MAX_NODES = 400;
const MAX_DEPTH = 64;
const MAX_LABEL = 40;

class TooBig extends Error {}

const clip = (s: string) => (s.length > MAX_LABEL ? s.slice(0, MAX_LABEL - 1) + '…' : s);

/** One graph for all of an artifact's branches, ending in the file itself. Identical steps
 * with identical inputs are one node. Null when nothing is recorded; tooBig past the limits. */
export function buildGraph(
	branches: Array<{ steps?: unknown }> | null | undefined,
	fileName: string
): { graph: ProvGraph | null; tooBig: boolean } {
	const nodes: Record<string, ProvNode> = Object.create(null);
	const ids = new Map<string, string>();
	const add = (step: ProvStep, ins: string[]) => {
		let sig: string;
		try {
			sig = JSON.stringify([step.skill, step.version ?? '', step.args ?? null, ins]);
		} catch {
			sig = `#${ids.size}`;
		}
		let id = ids.get(sig);
		if (!id) {
			if (ids.size >= MAX_NODES) throw new TooBig();
			id = `n${ids.size}`;
			ids.set(sig, id);
			nodes[id] = { label: clip(step.skill), step, in: ins };
		}
		return id;
	};
	// A chain is oldest first; a step whose input records its own history starts from that
	// history's last step, otherwise from the step before it.
	const chain = (steps: unknown, depth: number): string | null => {
		if (depth > MAX_DEPTH) throw new TooBig();
		let prev: string | null = null;
		for (const step of Array.isArray(steps) ? steps : []) {
			if (!step || typeof step !== 'object' || typeof step.skill !== 'string' || !step.skill)
				continue;
			const input = (step as ProvStep).input;
			const items = input == null ? [] : Array.isArray(input) ? input : [input];
			const ins: string[] = [];
			items.forEach((item, j) => {
				const history = item && typeof item === 'object' ? (item as any).history : null;
				const from = Array.isArray(history) && history.length ? chain(history, depth + 1) : null;
				if (from) ins.push(from);
				else if (j === 0 && prev) ins.push(prev);
			});
			if (!ins.length && prev) ins.push(prev);
			prev = add(step as ProvStep, [...new Set(ins)]);
		}
		return prev;
	};
	try {
		const sinks = (Array.isArray(branches) ? branches : []).map((b) => chain(b?.steps, 0));
		const ins = [...new Set(sinks.filter((s): s is string => !!s))];
		if (!ins.length) return { graph: null, tooBig: false };
		nodes.f = { label: clip(fileName || 'This file'), file: true, in: ins };
		// A step that a later join does not read leads nowhere; drop it.
		const keep: Record<string, ProvNode> = Object.create(null);
		const visit = (id: string) => {
			if (keep[id]) return;
			keep[id] = nodes[id];
			nodes[id].in.forEach(visit);
		};
		visit('f');
		return { graph: { nodes: keep, sink: 'f' }, tooBig: false };
	} catch (e) {
		if (e instanceof TooBig || e instanceof RangeError) return { graph: null, tooBig: true };
		throw e;
	}
}

const topo = (g: ProvGraph) => {
	const order: string[] = [];
	const seen = new Set<string>();
	const visit = (id: string) => {
		if (seen.has(id)) return;
		seen.add(id);
		g.nodes[id].in.forEach(visit);
		order.push(id);
	};
	visit(g.sink);
	return order;
};

/** The graph as drawn: each straight run of two or more plain steps (one input each, not a
 * plot, every step but the last feeding only the next) is one node unless its first step is
 * in `open`, in which case a handle node sits before it. */
export function viewGraph(g: ProvGraph, open: Set<string>): ProvView {
	const N = g.nodes;
	const out: Record<string, string[]> = Object.create(null);
	for (const id in N) N[id].in.forEach((i) => (out[i] ||= []).push(id));
	const plain = (id: string) =>
		!N[id].file && N[id].in.length === 1 && !/^plot/.test(N[id].step?.skill ?? '');
	const runOf: Record<string, number> = Object.create(null);
	const runs: string[][] = [];
	topo(g).forEach((id) => {
		if (!plain(id)) return;
		const p = N[id].in[0];
		if (runOf[p] !== undefined && out[p].length === 1) {
			runOf[id] = runOf[p];
			runs[runOf[p]].push(id);
		} else {
			runOf[id] = runs.length;
			runs.push([id]);
		}
	});
	const long = runs.filter((r) => r.length > 1);
	const rep: Record<string, string> = Object.create(null);
	const bands: string[][] = [];
	long.forEach((r) => {
		if (open.has(r[0])) bands.push([`h${r[0]}`, ...r]);
		else r.forEach((id) => (rep[id] = `r${r[0]}`));
	});
	const m = (i: string) => rep[i] || i;
	const nodes: Record<string, ProvNode> = Object.create(null);
	for (const id in N) if (!rep[id]) nodes[id] = { ...N[id], in: N[id].in.map(m) };
	long.forEach((r) => {
		if (open.has(r[0])) {
			nodes[`h${r[0]}`] = {
				label: '−',
				handle: r[0],
				count: r.length,
				in: nodes[r[0]].in
			};
			nodes[r[0]].in = [`h${r[0]}`];
		} else {
			nodes[`r${r[0]}`] = {
				label: `+ ${r.length} steps`,
				run: r,
				in: N[r[0]].in.map(m)
			};
		}
	});
	return { sink: g.sink, nodes, bands, heads: long.map((r) => r[0]) };
}

/** Columns: longest path from the sources, then every n-th use of the same skill along a
 * path shares one column (fetches all in the first), pushed right until stable. */
export function columns(g: ProvGraph): Record<string, number> {
	const N = g.nodes;
	const ids = Object.keys(N);
	const order = topo(g);
	const K = (id: string) => (N[id].run || N[id].handle ? 'run' : (N[id].step?.skill ?? ''));
	const memo = new Map<string, number>();
	const anc = (id: string, s: string): number => {
		const k = `${id}\n${s}`;
		if (!memo.has(k))
			memo.set(k, Math.max(0, ...N[id].in.map((i) => anc(i, s) + (K(i) === s ? 1 : 0))));
		return memo.get(k)!;
	};
	const key: Record<string, string> = Object.create(null);
	ids.forEach(
		(id) => (key[id] = N[id].file ? 'file' : N[id].in.length ? `${K(id)}#${anc(id, K(id))}` : 'src')
	);
	const col: Record<string, number> = Object.create(null);
	const push = () =>
		order.forEach((id) => (col[id] = Math.max(col[id] ?? 0, ...N[id].in.map((i) => col[i] + 1))));
	push();
	const base = { ...col };
	for (let t = 0; t < ids.length; t++) {
		const before = JSON.stringify(col);
		const most = new Map<string, number>();
		ids.forEach((id) => most.set(key[id], Math.max(most.get(key[id]) ?? 0, col[id])));
		ids.forEach((id) => (col[id] = most.get(key[id])!));
		push();
		if (JSON.stringify(col) === before) return col;
	}
	return base;
}

export type Kind = 'fetch' | 'step' | 'combine' | 'plot' | 'file' | 'run';
export const nodeKind = (o: ProvNode): Kind =>
	o.run || o.handle
		? 'run'
		: o.file
			? 'file'
			: !o.in.length
				? 'fetch'
				: /^plot/.test(o.step?.skill ?? '')
					? 'plot'
					: o.in.length > 1
						? 'combine'
						: 'step';

export const NODE_H = 20;
const PAD = 4;

export type Laid = {
	nodes: Array<{
		id: string;
		x: number;
		y: number;
		w: number;
		h: number;
		label: string;
		kind: Kind;
		/** A collapsed run, drawn as a stack. */
		stack: boolean;
	}>;
	edges: Array<{ d: string; width: number }>;
	bands: Array<{ x: number; y: number; w: number; h: number }>;
	W: number;
	H: number;
};

/** Positions from dagre, origin at the top left with a small margin. */
export function layoutGraph(V: ProvView, textWidth: (s: string) => number): Laid {
	const N = V.nodes;
	const col = columns(V);
	const dg = new Graph();
	dg.setGraph({ rankdir: 'LR', nodesep: 8, ranksep: 14, edgesep: 4 });
	dg.setDefaultEdgeLabel(() => ({}));
	for (const id in N)
		dg.setNode(id, {
			width: N[id].handle ? NODE_H : Math.ceil(textWidth(N[id].label)) + (N[id].run ? 14 : 10),
			height: NODE_H
		});
	for (const b in N)
		N[b].in.forEach((a) => dg.setEdge(a, b, { minlen: Math.max(1, col[b] - col[a]) }));
	// A hidden root keeps every source in the first column.
	dg.setNode('_root', { width: 0, height: 0 });
	for (const id in N) if (!N[id].in.length) dg.setEdge('_root', id, { weight: 10 });
	dagreLayout(dg, {});

	const box: Record<string, { x: number; y: number; w: number; h: number }> = Object.create(null);
	for (const id in N) {
		const n = dg.node(id);
		box[id] = {
			x: n.x - n.width / 2,
			y: n.y - n.height / 2,
			w: n.width,
			h: n.height
		};
	}
	const all = Object.values(box);
	const x0 = Math.min(...all.map((p) => p.x)) - PAD;
	const y0 = Math.min(...all.map((p) => p.y)) - PAD;
	// Edge width grows with the number of sources upstream.
	const src: Record<string, Set<string>> = Object.create(null);
	topo(V).forEach(
		(id) =>
			(src[id] = N[id].in.length ? new Set(N[id].in.flatMap((i) => [...src[i]])) : new Set([id]))
	);
	const path = line<{ x: number; y: number }>()
		.x((p) => p.x - x0)
		.y((p) => p.y - y0)
		.curve(curveBasis);
	const edges: Laid['edges'] = [];
	for (const b in N)
		N[b].in.forEach((a) =>
			edges.push({
				d: path(dg.edge(a, b, undefined).points) ?? '',
				width: Math.min(4, 1.25 + 0.4 * (src[a].size - 1))
			})
		);
	const bands = V.bands.map((r) => {
		const ps = r.map((id) => box[id]);
		const x = Math.min(...ps.map((p) => p.x)) - 3;
		const y = Math.min(...ps.map((p) => p.y)) - 3;
		return {
			x: x - x0,
			y: y - y0,
			w: Math.max(...ps.map((p) => p.x + p.w)) + 3 - x,
			h: Math.max(...ps.map((p) => p.y + p.h)) + 3 - y
		};
	});
	return {
		nodes: Object.keys(N).map((id) => ({
			id,
			...box[id],
			x: box[id].x - x0,
			y: box[id].y - y0,
			label: N[id].label,
			kind: nodeKind(N[id]),
			stack: !!N[id].run
		})),
		edges,
		bands,
		W: Math.max(...all.map((p) => p.x + p.w)) - x0 + PAD,
		H: Math.max(...all.map((p) => p.y + p.h)) - y0 + PAD
	};
}

/** A step's arguments as the chat's arguments viewer shows them, one row each, leaving out
 * arguments that were not set (null). */
export const argRows = (args: unknown): ToolArgRow[] => {
	if (!args || typeof args !== 'object' || Array.isArray(args)) return [];
	return Object.entries(args)
		.filter(([, value]) => value != null)
		.map(([key, value]) => {
			const { text, lang } = formatToolArgValue(value);
			return { key, value: text, lang, multiline: text.includes('\n') };
		});
};
