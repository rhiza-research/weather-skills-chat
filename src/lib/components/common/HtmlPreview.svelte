<script lang="ts">
	// Full-screen viewer for an HTML artifact, the counterpart of ImagePreview.
	// The figure has its own zoom and pan, so there is no panzoom here.
	import { onDestroy } from 'svelte';
	import HtmlArtifactFrame from './HtmlArtifactFrame.svelte';

	export let show = false;
	export let src = '';
	export let downloadUrl = '';
	export let title = '';

	let previewElement: HTMLElement | null = null;

	const fileName = () => (title || '').split(/[/\\]/).pop()?.trim() || 'figure.html';

	const download = () => {
		fetch(downloadUrl || src, {
			headers: { authorization: `Bearer ${localStorage.token}` }
		})
			.then((response) => response.blob())
			.then((blob) => {
				const objectUrl = window.URL.createObjectURL(blob);
				const link = document.createElement('a');
				link.href = objectUrl;
				link.download = fileName();
				document.body.appendChild(link);
				link.click();
				document.body.removeChild(link);
				window.URL.revokeObjectURL(objectUrl);
			})
			.catch((error) => console.error('Error downloading file:', error));
	};

	const handleKeyDown = (event: KeyboardEvent) => {
		if (event.key === 'Escape') show = false;
	};

	$: if (show && previewElement) {
		document.body.appendChild(previewElement);
		window.addEventListener('keydown', handleKeyDown);
		document.body.style.overflow = 'hidden';
	} else if (previewElement) {
		window.removeEventListener('keydown', handleKeyDown);
		if (previewElement.parentNode === document.body) document.body.removeChild(previewElement);
		document.body.style.overflow = 'unset';
	}

	onDestroy(() => {
		show = false;
		window.removeEventListener('keydown', handleKeyDown);
		if (previewElement?.parentNode === document.body) document.body.removeChild(previewElement);
	});
</script>

{#if show}
	<div
		bind:this={previewElement}
		class="modal fixed inset-0 bg-black text-white w-full h-screen flex flex-col z-9999 overflow-hidden overscroll-contain"
	>
		<div
			class="shrink-0 h-14 px-2 flex items-center justify-between gap-2 select-none relative z-20 bg-black border-b border-white/10"
		>
			<button
				type="button"
				class="p-3 rounded-md hover:bg-white/10"
				aria-label="Close"
				on:click={() => {
					show = false;
				}}
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					fill="none"
					viewBox="0 0 24 24"
					stroke-width="2"
					stroke="currentColor"
					class="w-6 h-6"
				>
					<path stroke-linecap="round" stroke-linejoin="round" d="M6 18 18 6M6 6l12 12" />
				</svg>
			</button>

			<div class="min-w-0 flex-1 truncate text-sm text-white/70">{fileName()}</div>

			<a
				href={src}
				target="_blank"
				rel="noopener noreferrer"
				class="p-3 rounded-md hover:bg-white/10"
				aria-label="Open in new tab"
				title="Open in new tab"
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					viewBox="0 0 20 20"
					fill="currentColor"
					class="w-6 h-6"
				>
					<path
						d="M11 3a1 1 0 1 0 0 2h2.586l-6.293 6.293a1 1 0 1 0 1.414 1.414L15 6.414V9a1 1 0 1 0 2 0V4a1 1 0 0 0-1-1h-5Z"
					/>
					<path
						d="M5 5a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2v-3a1 1 0 1 0-2 0v3H5V7h3a1 1 0 0 0 0-2H5Z"
					/>
				</svg>
			</a>

			<button
				type="button"
				class="p-3 rounded-md hover:bg-white/10"
				aria-label="Download"
				title="Download"
				on:click={download}
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					viewBox="0 0 20 20"
					fill="currentColor"
					class="w-6 h-6"
				>
					<path
						d="M10.75 2.75a.75.75 0 0 0-1.5 0v8.614L6.295 8.235a.75.75 0 1 0-1.09 1.03l4.25 4.5a.75.75 0 0 0 1.09 0l4.25-4.5a.75.75 0 0 0-1.09-1.03l-2.955 3.129V2.75Z"
					/>
					<path
						d="M3.5 12.75a.75.75 0 0 0-1.5 0v2.5A2.75 2.75 0 0 0 4.75 18h10.5A2.75 2.75 0 0 0 18 15.25v-2.5a.75.75 0 0 0-1.5 0v2.5c0 .69-.56 1.25-1.25 1.25H4.75c-.69 0-1.25-.56-1.25-1.25v-2.5Z"
					/>
				</svg>
			</button>
		</div>
		<div class="flex-1 min-h-0 w-full bg-white">
			<HtmlArtifactFrame {src} title={fileName()} className="h-full" lazy={false} />
		</div>
	</div>
{/if}
