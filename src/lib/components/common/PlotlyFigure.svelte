<script context="module" lang="ts">
	// One lazy load shared by every figure on the page.
	let loading: Promise<any> | null = null;
	const loadPlotly = () =>
		// @ts-ignore: the dist bundle ships no types
		(loading ??= import('plotly.js-dist-min').then((m) => m.default ?? m));
</script>

<script lang="ts">
	import { getContext, onMount, onDestroy } from 'svelte';

	const i18n = getContext('i18n');

	export let figure: { data: any[]; layout?: any; frames?: any[] };

	let el: HTMLDivElement;
	let plotly: any = null;

	// Fill the container instead of the size the skill picked for a PNG.
	const draw = (p: any, f: typeof figure) =>
		p.newPlot(el, {
			data: f.data,
			frames: f.frames,
			layout: { ...f.layout, width: undefined, height: undefined, autosize: true },
			config: { responsive: true, scrollZoom: true, showSendToCloud: false, displaylogo: false }
		});

	onMount(async () => {
		plotly = await loadPlotly();
	});
	onDestroy(() => plotly?.purge(el));

	$: if (plotly && el && figure) draw(plotly, figure);
</script>

{#if !plotly}
	<div class="text-xs text-gray-500 p-2">{$i18n.t('Loading chart...')}</div>
{/if}
<div bind:this={el} class="w-full h-full"></div>
