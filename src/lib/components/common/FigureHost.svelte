<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	// @ts-ignore: the dist bundle ships no types
	import plotlyUrl from 'plotly.js-dist-min/plotly.min.js?url';

	export let figure: any = null;

	let frame: HTMLIFrameElement;
	let src = '';
	let ready = false;
	let shown: any = null;

	// The host keeps one Plotly and repaints on each new figure.
	$: if (ready && figure && figure !== shown && frame?.contentWindow) {
		shown = figure;
		frame.contentWindow.postMessage({ type: 'figure', figure }, '*');
	}

	const onMessage = (event: MessageEvent) => {
		if (event.source !== frame?.contentWindow) return;
		const data = event.data;
		if (data?.type === 'ready') ready = true;
		else if (data?.type === 'error') console.error('figure host:', data.message);
	};

	onMount(() => {
		const url = new URL(plotlyUrl, location.href).href;
		src = `/figure-host.html?plotly=${encodeURIComponent(url)}`;
		addEventListener('message', onMessage);
	});
	onDestroy(() => removeEventListener('message', onMessage));
</script>

<iframe
	bind:this={frame}
	{src}
	title="Figure"
	sandbox="allow-scripts allow-downloads"
	class="w-full h-full border-0"
></iframe>
