<script lang="ts">
	import { onDestroy } from 'svelte';
	import Spinner from './Spinner.svelte';

	// An HTML artifact (for example a Plotly figure) in a sandboxed iframe.
	//
	// No allow-same-origin: the page gets its own opaque origin, so its scripts
	// cannot read this app's storage or cookies or call its API as the user.
	// The view route sends the same sandbox as a CSP header. allow-downloads
	// keeps Plotly's "download plot as PNG" button working.
	//
	// A Plotly figure saved at a fixed size reports that size (the view route
	// appends a read-only script). The page is then drawn at exactly that size,
	// as the skill made it, and the whole frame is scaled to fit, like an
	// image. Hover and zoom still work: the browser maps the pointer through the
	// scale. A scaled page does not scroll: Plotly's own page sets
	// html, body { height: 100% } with an 8px body margin, so it always runs 8px
	// past whatever height it is given. Pages that report nothing (responsive
	// figures, other HTML) fill the space and scroll as usual.
	//   width:   chat messages. Full width, height capped so a tall figure
	//            does not take over the chat.
	//   contain: sidebar and popup. The largest size that fits.
	//
	// The frame stays invisible until its layout is settled: until the page
	// reports its size, or shortly after it loads if it reports none.
	// Otherwise the figure is first drawn at the left of a full-width frame
	// and then jumps and reshapes as it is scaled.
	export let src = '';
	export let title = 'Interactive figure';
	export let lazy = true;
	export let fit: 'width' | 'contain' = 'width';
	export let defaultHeight = 450;
	export let maxHeight = 640;
	export let maxScale = 2;

	let iframe: HTMLIFrameElement | null = null;
	let boxWidth = 0;
	let boxHeight = 0;
	let viewportHeight = 0;
	let pageWidth = 0;
	let pageHeight = 0;
	let revealed = false;
	let revealTimer: ReturnType<typeof setTimeout> | null = null;

	const clearRevealTimer = () => {
		if (revealTimer) clearTimeout(revealTimer);
		revealTimer = null;
	};

	const onMessage = (event: MessageEvent) => {
		if (!iframe || event.source !== iframe.contentWindow) return;
		const data = event.data;
		if (!data || data.type !== 'weather-skills:figure-size') return;
		const width = Number(data.width);
		const height = Number(data.height);
		if (width > 0 && height > 0 && width < 20000 && height < 20000) {
			pageWidth = width;
			pageHeight = height;
			clearRevealTimer();
			revealed = true;
		}
	};

	// The page's own size report runs when it finishes loading, and its
	// message can arrive just after this event. Pages that never report
	// (responsive figures, other HTML) are shown after that short grace.
	const onLoad = () => {
		if (revealed) return;
		clearRevealTimer();
		revealTimer = setTimeout(() => (revealed = true), 150);
	};

	// A new src is a new page.
	const startPage = () => {
		clearRevealTimer();
		pageWidth = 0;
		pageHeight = 0;
		revealed = false;
	};
	$: src, startPage();

	onDestroy(clearRevealTimer);

	$: fixed = pageWidth > 0 && pageHeight > 0;
	$: heightCap = Math.max(200, Math.min(maxHeight, (viewportHeight || maxHeight) * 0.7));
	$: scale = !fixed
		? 1
		: fit === 'width'
			? Math.min(boxWidth / pageWidth, heightCap / pageHeight, maxScale)
			: Math.min(boxWidth / pageWidth, boxHeight / pageHeight, maxScale);
	$: scaled = fixed && boxWidth > 0 && (fit === 'width' || boxHeight > 0);
	$: wrapperStyle = scaled
		? `width: ${Math.floor(pageWidth * scale)}px; height: ${Math.floor(pageHeight * scale)}px;`
		: `width: 100%; height: ${fit === 'contain' ? '100%' : `${defaultHeight}px`};`;
	$: frameStyle = scaled
		? `width: ${pageWidth}px; height: ${pageHeight}px; transform: scale(${scale}); transform-origin: 0 0;`
		: 'width: 100%; height: 100%;';
</script>

<svelte:window on:message={onMessage} bind:innerHeight={viewportHeight} />

<!-- One iframe throughout: switching to the scaled layout must not reload the page. -->
<div
	class="flex w-full items-center justify-center {fit === 'contain' ? 'h-full' : ''}"
	bind:clientWidth={boxWidth}
	bind:clientHeight={boxHeight}
>
	<div class="relative shrink-0 overflow-hidden bg-white" style={wrapperStyle}>
		<iframe
			bind:this={iframe}
			{src}
			{title}
			class="block border-0 bg-white {scaled ? 'absolute left-0 top-0' : ''}"
			style="{frameStyle} opacity: {revealed ? 1 : 0}; transition: opacity 120ms;"
			scrolling={scaled ? 'no' : undefined}
			sandbox="allow-scripts allow-downloads"
			referrerpolicy="no-referrer"
			loading={lazy ? 'lazy' : 'eager'}
			on:load={onLoad}
		/>
		{#if !revealed}
			<div class="pointer-events-none absolute inset-0 flex items-center justify-center">
				<Spinner className="size-5 text-gray-400" />
			</div>
		{/if}
	</div>
</div>
