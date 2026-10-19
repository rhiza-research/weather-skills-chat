<script lang="ts">
	// A markdown link to an HTML artifact: a click opens it full screen in the
	// sandboxed viewer. A middle-click or "open in new tab" goes to the view
	// route, whose CSP header sandboxes it there too.
	import HtmlPreview from './HtmlPreview.svelte';

	export let src = '';
	export let downloadUrl = '';
	export let title = '';
	export let linkTitle: string | undefined = undefined;

	let showPreview = false;
</script>

<a
	href={src}
	title={linkTitle}
	target="_blank"
	rel="noopener noreferrer"
	on:click={(e) => {
		if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
		e.preventDefault();
		showPreview = true;
	}}><slot /></a
><HtmlPreview bind:show={showPreview} {src} {downloadUrl} {title} />
