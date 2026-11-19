<script lang="ts">
	import { getContext, onDestroy, onMount, tick } from 'svelte';
	import { select, zoom as d3zoom, zoomIdentity, zoomTransform, type ZoomTransform } from 'd3';
	import Tooltip from '../common/Tooltip.svelte';
	import ProvenanceArgs from './ProvenanceArgs.svelte';
	import {
		buildGraph,
		layoutGraph,
		viewGraph,
		type Laid,
		type ProvGraph,
		type ProvView
	} from '$lib/chat/provenanceGraph';

	const i18n = getContext('i18n');

	export let branches: Array<any> = [];
	export let fileName = '';
	// Fill the parent's height (artifact panel, full screen); otherwise up to maxHeight tall.
	export let fill = false;
	export let maxHeight = 220;
	// Full screen: a graph smaller than the view starts scaled up to fill it, up to K_MAX.
	export let grow = false;

	// Zoom: never below where the whole graph fits, at least 75% when it fits there, and up to 2x.
	// Under a chat image a graph that fits whole does not zoom, so the wheel scrolls the chat.
	const K_HOME = 0.75;
	const K_MAX = 2;
	const POP_MAX = 360;

	let graph: ProvGraph | null = null;
	let tooBig = false;
	// Svelte hands an object prop over again on every parent update; rebuild only on a new one.
	let builtFrom: [unknown, string] | null = null;
	$: if (!builtFrom || builtFrom[0] !== branches || builtFrom[1] !== fileName) {
		builtFrom = [branches, fileName];
		({ graph, tooBig } = buildGraph(branches, fileName));
	}

	let open = new Set<string>();
	let V: ProvView | null = null;
	let L: Laid | null = null;
	let full: { W: number; H: number } | null = null;
	let prev: ZoomTransform | null = null;
	let fit = 1;
	let zoomable = false;
	let home = zoomIdentity;

	let svgEl: SVGSVGElement;
	let panEl: SVGGElement;
	let measureEl: SVGTextElement;
	let viewEl: HTMLDivElement;
	let viewH = 0;
	let mounted = false;

	$: height = fill ? viewH : Math.max(32, Math.min(maxHeight, Math.ceil(L?.H ?? 32)));

	const textWidth = (s: string) => {
		measureEl.textContent = s;
		return measureEl.getComputedTextLength() || s.length * 6.3;
	};

	let kRange: [number, number] = [1, 1];
	const zoom = d3zoom<SVGSVGElement, unknown>()
		// The page scrolls when the wheel would push past a zoom limit.
		.filter((ev) => {
			if (ev.type !== 'wheel') return !ev.button;
			const [k0, k1] = kRange;
			const k = zoomTransform(svgEl).k;
			return k1 > k0 && (ev.deltaY > 0 ? k > k0 + 1e-3 : k < k1 - 1e-3);
		})
		.on('zoom', (ev) => {
			prev = ev.transform;
			panEl?.setAttribute('transform', ev.transform.toString());
			place();
		});

	const applyZoom = () => {
		if (!L || !svgEl) return;
		const bw = svgEl.clientWidth || svgEl.getBoundingClientRect().width;
		const bh = height;
		if (!bw || !bh) return;
		fit = Math.min(bw / L.W, bh / L.H);
		const kmin = Math.min(1, fit);
		const kmax = fill || (full && Math.min(bw / full.W, bh / full.H) < 1) ? K_MAX : 1;
		zoomable = kmax > kmin;
		kRange = [kmin, kmax];
		const kh = Math.max(kmin, Math.min(grow ? K_MAX : 1, Math.max(K_HOME, fit)));
		home = zoomIdentity
			.translate(Math.max(0, (bw - L.W * kh) / 2), Math.max(0, (bh - L.H * kh) / 2))
			.scale(kh);
		zoom
			.scaleExtent([kmin, kmax])
			.extent([
				[0, 0],
				[bw, bh]
			])
			.translateExtent([
				[0, 0],
				[L.W, L.H]
			]);
		// Keep the view across expand, collapse and resize, clamped to the new graph.
		const keep = prev
			? zoomIdentity.translate(prev.x, prev.y).scale(Math.max(kmin, Math.min(kmax, prev.k)))
			: home;
		select(svgEl).call(zoom.transform, keep).call(zoom.translateBy, 0, 0);
	};

	const draw = async () => {
		if (!graph || !measureEl) return;
		V = viewGraph(graph, open);
		try {
			L = layoutGraph(V, textWidth);
		} catch (e) {
			// Crafted provenance can trip dagre; the text view still reads it.
			console.error(e);
			V = L = null;
			tooBig = true;
			return;
		}
		full ??= { W: L.W, H: L.H };
		if (cur && !V.nodes[cur]) hideNow();
		await tick();
		applyZoom();
	};

	// Every step shows when the whole graph fits; runs start collapsed when it does not.
	let shownGraph: ProvGraph | null = null;
	const start = async () => {
		shownGraph = graph;
		pin = null;
		hideNow();
		prev = null;
		full = null;
		L = null;
		if (!graph) return;
		open = new Set(viewGraph(graph, new Set()).heads);
		await draw();
		if (fit < 1 && open.size) {
			open = new Set();
			prev = null;
			await draw();
		}
	};
	$: if (mounted && graph !== shownGraph) start();

	const toggleAll = () => {
		if (!V || !graph) return;
		const anyClosed = Object.values(V.nodes).some((o) => o.run);
		open = anyClosed ? new Set(V.heads) : new Set();
		draw();
	};
	$: anyClosed = !!V && Object.values(V.nodes).some((o) => o.run);

	// Arguments popover: on hover or focus, pinned by a click. It lives on <body> so the
	// panel's overflow does not cut it off.
	let cur: string | null = null;
	let pin: string | null = null;
	let popEl: HTMLDivElement;
	let popStyle = '';
	let hideTimer: ReturnType<typeof setTimeout> | undefined;
	let hoverTimer: ReturnType<typeof setTimeout> | undefined;
	// Hover waits a moment, so the pointer can cross the graph without opening every node.
	const HOVER_DELAY = 250;
	const hoverIn = (id: string) => {
		clearTimeout(hoverTimer);
		hoverTimer = setTimeout(() => show(id), HOVER_DELAY);
	};
	const hoverOut = () => {
		clearTimeout(hoverTimer);
		hide();
	};

	const portal = (node: HTMLElement) => {
		document.body.appendChild(node);
		return { destroy: () => node.remove() };
	};

	const nodeRect = () =>
		cur
			? panEl?.querySelector(`[data-id="${cur}"] rect:last-of-type`)?.getBoundingClientRect()
			: null;

	const room = () => {
		const r = nodeRect();
		if (!r) return POP_MAX;
		return Math.max(120, Math.min(POP_MAX, Math.max(r.top, window.innerHeight - r.bottom) - 14));
	};

	// Long values first share the popover's height, so every name shows the start of its value;
	// if it is still too tall, the visible part ends on a whole argument.
	const fitPop = () => {
		if (!popEl) return;
		const max = room();
		const codes = [...popEl.querySelectorAll<HTMLElement>('pre')];
		popEl.style.maxHeight = `${max}px`;
		codes.forEach((c) => (c.style.maxHeight = ''));
		if (popEl.scrollHeight <= max) return;
		const fixed = popEl.scrollHeight - codes.reduce((a, c) => a + c.offsetHeight, 0);
		codes.forEach(
			(c) =>
				(c.style.maxHeight = `${Math.max(54, Math.floor((max - fixed) / Math.max(1, codes.length)))}px`)
		);
		if (popEl.scrollHeight <= max) return;
		const top = popEl.getBoundingClientRect().top;
		let cut = 0;
		popEl.querySelectorAll('[data-row]').forEach((row) => {
			const b = row.getBoundingClientRect().bottom - top;
			if (b <= max - 8) cut = b;
		});
		if (cut) popEl.style.maxHeight = `${Math.ceil(cut) + 1}px`;
	};

	const place = () => {
		const r = nodeRect();
		if (!r || !popEl) return;
		const w = popEl.offsetWidth;
		const h = popEl.offsetHeight;
		const left = Math.max(4, Math.min(r.left, window.innerWidth - w - 4));
		const top =
			r.top - h - 6 >= 4 ? r.top - h - 6 : Math.min(r.bottom + 6, window.innerHeight - h - 4);
		popStyle = `left:${Math.round(left)}px;top:${Math.round(top)}px`;
	};

	const show = async (id: string) => {
		clearTimeout(hideTimer);
		const fresh = cur !== id;
		cur = id;
		await tick();
		if (fresh && popEl) {
			popEl.scrollTop = 0;
			fitPop();
		}
		place();
	};
	const hideNow = () => {
		clearTimeout(hideTimer);
		if (pin && V?.nodes[pin]) show(pin);
		else cur = null;
	};
	// A short delay lets the pointer travel from a node into its popover to scroll it.
	const hide = () => {
		clearTimeout(hideTimer);
		hideTimer = setTimeout(hideNow, 160);
	};

	const act = (id: string) => {
		const o = V?.nodes[id];
		if (!o) return;
		if (o.run) {
			open = new Set([...open, o.run[0]]);
			draw();
		} else if (o.handle) {
			open.delete(o.handle);
			open = open;
			draw();
		} else {
			pin = pin === id ? null : id;
			show(id);
		}
	};

	$: popNode = cur && V ? V.nodes[cur] : null;

	let ro: ResizeObserver | undefined;
	let resizeTimer: ReturnType<typeof setTimeout> | undefined;
	onMount(async () => {
		select(svgEl).call(zoom).on('dblclick.zoom', null);
		ro = new ResizeObserver(() => {
			clearTimeout(resizeTimer);
			resizeTimer = setTimeout(applyZoom, 100);
		});
		ro.observe(viewEl);
		// Labels are measured in the app font.
		await document.fonts?.ready;
		mounted = true;
	});
	onDestroy(() => {
		ro?.disconnect();
		clearTimeout(resizeTimer);
		clearTimeout(hideTimer);
		clearTimeout(hoverTimer);
	});

	const scrollWindow = () => cur && place();
</script>

<svelte:window on:scroll|capture={scrollWindow} />

<div class="flex flex-col min-w-0 {fill ? 'h-full min-h-0' : ''}">
	<div class="flex items-center justify-between gap-2 mb-1 min-h-5">
		<div class="flex items-center gap-2"><slot name="lead" /></div>
		<div class="flex items-center gap-2.5">
			{#if V?.heads.length}
				<button
					type="button"
					class="flex items-center gap-1 text-xs text-muted hover:text-gray-700 dark:hover:text-gray-300 whitespace-nowrap transition"
					on:click={toggleAll}
				>
					<svg
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="2"
						stroke-linecap="round"
						stroke-linejoin="round"
						class="size-3.5"
						aria-hidden="true"
					>
						<path
							d={anyClosed
								? 'M9 8.25 5.25 12 9 15.75M15 8.25 18.75 12 15 15.75'
								: 'M5.25 8.25 9 12l-3.75 3.75M18.75 8.25 15 12l3.75 3.75'}
						/>
					</svg>
					{anyClosed ? $i18n.t('Expand all') : $i18n.t('Collapse all')}
				</button>
			{/if}
			{#if zoomable}
				<Tooltip content={$i18n.t('Reset view')}>
					<!-- Plotly's "Reset axes" home icon. -->
					<button
						type="button"
						class="block px-0.5 text-black/30 hover:text-black/70 dark:text-white/30 dark:hover:text-white/70"
						aria-label={$i18n.t('Reset view')}
						on:click={() => select(svgEl).call(zoom.transform, home)}
					>
						<svg viewBox="0 0 928.6 1000" class="size-[15px] fill-current" aria-hidden="true">
							<path
								transform="matrix(1 0 0 -1 0 850)"
								d="m786 296v-267q0-15-11-26t-25-10h-214v214h-143v-214h-214q-15 0-25 10t-11 26v267q0 1 0 2t0 2l321 264 321-264q1-1 1-4z m124 39l-34-41q-5-5-12-6h-2q-7 0-12 3l-386 322-386-322q-7-4-13-4-7 2-12 7l-35 41q-4 5-3 13t6 12l401 334q18 15 42 15t43-15l136-114v109q0 8 5 13t13 5h107q8 0 13-5t5-13v-227l122-102q5-5 6-12t-4-13z"
							/>
						</svg>
					</button>
				</Tooltip>
			{/if}
			<slot name="trail" />
		</div>
	</div>

	<div
		bind:this={viewEl}
		bind:clientHeight={viewH}
		class={fill ? 'flex-1 min-h-0 overflow-hidden' : ''}
	>
		{#if tooBig}
			<div class="text-xs text-muted py-2">
				{$i18n.t('This provenance cannot be drawn as a graph. Switch to Text to read it.')}
			</div>
		{/if}
		<!-- svelte-ignore a11y-click-events-have-key-events a11y-no-noninteractive-element-interactions -->
		<svg
			bind:this={svgEl}
			class="block w-full cursor-grab touch-none select-none pv"
			height={tooBig ? 0 : height}
			role="img"
			aria-label={$i18n.t('Provenance graph')}
			on:click={() => {
				pin = null;
				hideNow();
			}}
		>
			<text bind:this={measureEl} class="lbl" visibility="hidden" x="-9999" y="-9999" />
			<g bind:this={panEl}>
				{#if L}
					{#each L.bands as b}
						<rect class="band" x={b.x} y={b.y} width={b.w} height={b.h} rx={6} />
					{/each}
					{#each L.edges as e}
						<path class="edge" d={e.d} stroke-width={e.width} />
					{/each}
					{#each L.nodes as n (n.id)}
						<g
							class="node k-{n.kind}"
							class:on={cur === n.id}
							data-id={n.id}
							tabindex="0"
							role="button"
							aria-label={n.label}
							on:mouseenter={(ev) => !ev.buttons && hoverIn(n.id)}
							on:mouseleave={hoverOut}
							on:focus={() => show(n.id)}
							on:blur={hide}
							on:click|stopPropagation={() => act(n.id)}
							on:keydown={(ev) => {
								if (ev.key === 'Enter' || ev.key === ' ') {
									ev.preventDefault();
									act(n.id);
								}
							}}
						>
							{#if n.stack}
								<rect x={n.x + 2.5} y={n.y + 2.5} width={n.w} height={n.h} rx={4} />
							{/if}
							<rect x={n.x} y={n.y} width={n.w} height={n.h} rx={4} />
							<text
								class="lbl"
								x={n.x + n.w / 2}
								y={n.y + n.h / 2}
								text-anchor="middle"
								dominant-baseline="central">{n.label}</text
							>
						</g>
					{/each}
				{/if}
			</g>
		</svg>
	</div>
</div>

{#if popNode}
	<!-- svelte-ignore a11y-no-static-element-interactions -->
	<div
		use:portal
		bind:this={popEl}
		class="fixed z-[10000] w-72 overflow-y-auto rounded-lg border border-line-strong bg-white dark:bg-gray-850 px-2.5 py-2 text-xs leading-snug text-body shadow-md"
		style={popStyle}
		on:mouseenter={() => clearTimeout(hideTimer)}
		on:mouseleave={hide}
	>
		{#if popNode.handle}
			<div class="font-medium">
				{$i18n.t('Collapse these {{COUNT}} steps', { COUNT: popNode.count })}
			</div>
		{:else if popNode.run}
			<div class="font-medium break-words">
				{popNode.run.map((id) => graph?.nodes[id]?.step?.skill).join(' → ')}
			</div>
			<div class="text-muted">{$i18n.t('Expand to view arguments')}</div>
		{:else}
			<div class="font-medium break-words">
				{popNode.file && fileName ? fileName : (popNode.step?.skill ?? popNode.label)}
			</div>
			<div class="text-muted">
				{popNode.file
					? $i18n.t('This file')
					: popNode.step?.version
						? $i18n.t('Version {{VERSION}}', { VERSION: popNode.step.version })
						: ''}{pin === cur ? ` · ${$i18n.t('pinned')}` : ''}
			</div>
			{#if !popNode.file}
				<ProvenanceArgs args={popNode.step?.args} />
			{/if}
		{/if}
	</div>
{/if}

<style>
	/* Pastel tints of the weather-skills plots' palette: beige, green, blue and lavender along
	   the pipeline, and slate (their water) for the file and the edges. */
	.pv :global(text.lbl) {
		font-size: 11px;
	}
	.edge {
		fill: none;
		stroke: #a7b3c0;
		stroke-opacity: 0.8;
		stroke-linecap: round;
		pointer-events: none;
	}
	.band {
		fill: rgba(112, 128, 144, 0.04);
		stroke: #d5d9de;
		stroke-width: 0.75;
		stroke-dasharray: 3 2;
		pointer-events: none;
	}
	.node {
		cursor: pointer;
		outline: none;
	}
	.node rect {
		stroke-width: 0.75;
	}
	.node.on rect,
	.node:focus-visible rect {
		stroke-width: 1.75;
	}
	.k-fetch rect {
		fill: #f6e8c3;
		stroke: #c9b07a;
	}
	.k-fetch text {
		fill: #5c4718;
	}
	.k-step rect {
		fill: #e4f4e0;
		stroke: #9cc894;
	}
	.k-step text {
		fill: #2f5a2a;
	}
	.k-combine rect {
		fill: #e3edfa;
		stroke: #98b6e2;
	}
	.k-combine text {
		fill: #26497a;
	}
	.k-plot rect {
		fill: #ece8fb;
		stroke: #b3a8e6;
	}
	.k-plot text {
		fill: #463a8a;
	}
	.k-file rect {
		fill: #e3e8ee;
		stroke: #8796a6;
	}
	.k-file text {
		fill: #2f3d4b;
		font-weight: 600;
	}
	.k-run rect {
		fill: #fff;
		stroke: #b4b4b4;
		stroke-dasharray: 3 2;
	}
	.k-run text {
		fill: #676767;
	}

	:global(.dark) .edge {
		stroke: #6f7d8b;
	}
	:global(.dark) .band {
		fill: rgba(112, 128, 144, 0.06);
		stroke: #4e4e4e;
	}
	:global(.dark) .k-fetch rect {
		fill: #3a3326;
		stroke: #b8a172;
	}
	:global(.dark) .k-fetch text {
		fill: #f6e8c3;
	}
	:global(.dark) .k-step rect {
		fill: #223225;
		stroke: #7fa978;
	}
	:global(.dark) .k-step text {
		fill: #d6eed1;
	}
	:global(.dark) .k-combine rect {
		fill: #1f2b3b;
		stroke: #7f9fcc;
	}
	:global(.dark) .k-combine text {
		fill: #d9e5f7;
	}
	:global(.dark) .k-plot rect {
		fill: #2a2740;
		stroke: #9d93d2;
	}
	:global(.dark) .k-plot text {
		fill: #e4dff8;
	}
	:global(.dark) .k-file rect {
		fill: #2b333d;
		stroke: #8796a6;
	}
	:global(.dark) .k-file text {
		fill: #e3e8ee;
	}
	:global(.dark) .k-run rect {
		fill: #171717;
		stroke: #676767;
	}
	:global(.dark) .k-run text {
		fill: #b4b4b4;
	}
</style>
