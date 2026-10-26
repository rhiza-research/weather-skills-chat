<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	// @ts-ignore: the dist bundle ships no types
	import plotlyUrl from 'plotly.js-dist-min/plotly.min.js?url';

	let frame: HTMLIFrameElement;
	let src = '';
	let ready = false;
	let pending: any = null;
	let seq = 0;

	export function render(value: any) {
		if (!ready) {
			pending = value;
			return;
		}
		if (!frame?.contentWindow) return;
		frame.contentWindow.postMessage({ type: 'figure', id: ++seq, figure: value }, '*');
	};

	const onMessage = (event: MessageEvent) => {
		if (event.source !== frame?.contentWindow) return;
		const data = event.data;
		if (data?.type === 'ready') {
			ready = true;
			const value = pending;
			pending = null;
			if (value) render(value);
		} else if (data?.type === 'error') {
			console.error('figure host:', data.message);
		}
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
