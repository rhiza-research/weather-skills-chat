<script lang="ts">
	import ArrowsPointingOut from '$lib/components/icons/ArrowsPointingOut.svelte';
	import { getContext } from 'svelte';
	// An HTML artifact shown in a message: a lazy, fixed-height frame with an
	// expand button that opens it full screen.
	import HtmlArtifactFrame from './HtmlArtifactFrame.svelte';
	import HtmlPreview from './HtmlPreview.svelte';

	const i18n = getContext('i18n');

	export let src = '';
	export let downloadUrl = '';
	export let title = '';

	let showPreview = false;
</script>

<div
	class="relative my-2 w-full max-w-3xl overflow-hidden rounded-lg border border-line-strong"
>
	<HtmlArtifactFrame {src} {title} fit="width" />
	<button
		type="button"
		class="absolute right-2 top-2 rounded-xl bg-black/60 p-1.5 text-white hover:bg-black/80"
		aria-label={$i18n.t('Expand')}
		title={$i18n.t('Expand')}
		on:click={() => {
			showPreview = true;
		}}
	>
		<ArrowsPointingOut className="size-4" strokeWidth="2" />
	</button>
</div>

<HtmlPreview bind:show={showPreview} {src} {downloadUrl} {title} />
