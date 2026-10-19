<script lang="ts">
	// An HTML artifact (for example a Plotly figure) in a sandboxed iframe.
	//
	// No allow-same-origin: the page gets its own opaque origin, so its scripts
	// cannot read this app's storage or cookies or call its API as the user.
	// The view route sends the same sandbox as a CSP header. allow-downloads
	// keeps Plotly's "download plot as PNG" button working.
	//
	// The view route also fits a Plotly figure to the frame and posts the size
	// it was made for. fit uses that to keep the figure's shape:
	//   width:   full width of the container, height from the aspect ratio,
	//            capped (and then narrowed) so a tall figure does not take over
	//            the chat.
	//   contain: the largest size that fits the container (sidebar, popup).
	//   none:    the className decides the size.
	export let src = '';
	export let title = 'Interactive figure';
	export let className = '';
	export let lazy = true;
	export let fit: 'none' | 'width' | 'contain' = 'none';
	export let defaultHeight = 450;
	export let maxHeight = 640;

	let iframe: HTMLIFrameElement | null = null;
	let boxWidth = 0;
	let boxHeight = 0;
	let viewportHeight = 0;
	let figureWidth = 0;
	let figureHeight = 0;

	const onMessage = (event: MessageEvent) => {
		if (!iframe || event.source !== iframe.contentWindow) return;
		const data = event.data;
		if (!data || data.type !== 'weather-skills:figure-size') return;
		const width = Number(data.width);
		const height = Number(data.height);
		if (width > 0 && height > 0 && width < 100000 && height < 100000) {
			figureWidth = width;
			figureHeight = height;
		}
	};

	// A new src is a new figure.
	$: src, (figureWidth = 0), (figureHeight = 0);

	$: frameStyle = (() => {
		const known = figureWidth > 0 && figureHeight > 0;
		if (fit === 'width') {
			if (!known || boxWidth <= 0) return `width: 100%; height: ${defaultHeight}px;`;
			const cap = Math.max(200, Math.min(maxHeight, (viewportHeight || maxHeight) * 0.7));
			let height = (boxWidth * figureHeight) / figureWidth;
			let width = boxWidth;
			if (height > cap) {
				height = cap;
				width = (height * figureWidth) / figureHeight;
			}
			return `width: ${Math.round(width)}px; height: ${Math.round(height)}px;`;
		}
		if (fit === 'contain') {
			if (!known || boxWidth <= 0 || boxHeight <= 0) return 'width: 100%; height: 100%;';
			const scale = Math.min(boxWidth / figureWidth, boxHeight / figureHeight);
			return `width: ${Math.round(figureWidth * scale)}px; height: ${Math.round(figureHeight * scale)}px;`;
		}
		return '';
	})();
</script>

<svelte:window on:message={onMessage} bind:innerHeight={viewportHeight} />

<div
	class="flex w-full items-center justify-center {fit === 'contain' ? 'h-full' : ''}"
	bind:clientWidth={boxWidth}
	bind:clientHeight={boxHeight}
>
	<iframe
		bind:this={iframe}
		{src}
		{title}
		class="block border-0 bg-white {fit === 'none' ? `w-full ${className}` : className}"
		style={frameStyle}
		sandbox="allow-scripts allow-downloads"
		referrerpolicy="no-referrer"
		loading={lazy ? 'lazy' : 'eager'}
	/>
</div>
