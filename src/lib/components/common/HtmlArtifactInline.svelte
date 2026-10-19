<script lang="ts">
	// An HTML artifact shown in a message: a lazy, fixed-height frame with an
	// expand button that opens it full screen.
	import HtmlArtifactFrame from './HtmlArtifactFrame.svelte';
	import HtmlPreview from './HtmlPreview.svelte';

	export let src = '';
	export let downloadUrl = '';
	export let title = '';

	let showPreview = false;
</script>

<div
	class="relative my-2 w-full max-w-3xl overflow-hidden rounded-lg border border-gray-200 dark:border-gray-800"
>
	<HtmlArtifactFrame {src} {title} fit="width" />
	<button
		type="button"
		class="absolute right-2 top-2 rounded-md bg-black/60 p-1.5 text-white hover:bg-black/80"
		aria-label="Expand"
		title="Expand"
		on:click={() => {
			showPreview = true;
		}}
	>
		<svg
			xmlns="http://www.w3.org/2000/svg"
			fill="none"
			viewBox="0 0 24 24"
			stroke-width="2"
			stroke="currentColor"
			class="size-4"
		>
			<path
				stroke-linecap="round"
				stroke-linejoin="round"
				d="M3.75 3.75v4.5m0-4.5h4.5m-4.5 0L9 9M3.75 20.25v-4.5m0 4.5h4.5m-4.5 0L9 15M20.25 3.75h-4.5m4.5 0v4.5m0-4.5L15 9m5.25 11.25h-4.5m4.5 0v-4.5m0 4.5L15 15"
			/>
		</svg>
	</button>
</div>

<HtmlPreview bind:show={showPreview} {src} {downloadUrl} {title} />
