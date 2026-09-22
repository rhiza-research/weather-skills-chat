<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import panzoom, { type PanZoom } from 'panzoom';

	export let show = false;
	export let src = '';
	export let alt = '';

	let mounted = false;

	let previewElement = null;

	let instance: PanZoom;

	let sceneParentElement: HTMLElement;
	let sceneElement: HTMLElement;

	$: if (sceneElement) {
		instance = panzoom(sceneElement, {
			bounds: true,
			boundsPadding: 0.1,

			zoomSpeed: 0.065
		});
	}
	const resetPanZoomViewport = () => {
		instance.moveTo(0, 0);
		instance.zoomAbs(0, 0, 1);
		console.log(instance.getTransform());
	};

	const downloadBasename = (name: string, url: string) => {
		const fromAlt = (name || '').split(/[/\\]/).pop()?.trim() || '';
		if (fromAlt && /\.[a-z0-9]{2,5}$/i.test(fromAlt)) {
			return fromAlt;
		}
		try {
			const parsed = new URL(url, window.location.origin);
			if (parsed.protocol !== 'blob:') {
				const pathParam = parsed.searchParams.get('path');
				if (pathParam) {
					const base = pathParam.split('/').pop();
					if (base) return base;
				}
				const last = parsed.pathname.split('/').pop() || '';
				if (last.includes('.')) return last;
			}
		} catch {
			// ignore invalid URLs
		}
		if (fromAlt) return `${fromAlt}.png`;
		return 'image.png';
	};

	const downloadImage = (url: string, filename: string) => {
		fetch(url)
			.then((response) => response.blob())
			.then((blob) => {
				const objectUrl = window.URL.createObjectURL(blob);
				const link = document.createElement('a');
				link.href = objectUrl;
				link.download = filename;
				document.body.appendChild(link);
				link.click();
				document.body.removeChild(link);
				window.URL.revokeObjectURL(objectUrl);
			})
			.catch((error) => console.error('Error downloading image:', error));
	};

	const handleKeyDown = (event: KeyboardEvent) => {
		if (event.key === 'Escape') {
			console.log('Escape');
			show = false;
		}
	};

	onMount(() => {
		mounted = true;
	});

	$: if (show && previewElement) {
		document.body.appendChild(previewElement);
		window.addEventListener('keydown', handleKeyDown);
		document.body.style.overflow = 'hidden';
	} else if (previewElement) {
		window.removeEventListener('keydown', handleKeyDown);
		document.body.removeChild(previewElement);
		document.body.style.overflow = 'unset';
	}

	onDestroy(() => {
		show = false;

		if (previewElement) {
			document.body.removeChild(previewElement);
		}
	});
</script>

{#if show}
	<!-- svelte-ignore a11y-click-events-have-key-events -->
	<!-- svelte-ignore a11y-no-static-element-interactions -->
	<div
		bind:this={previewElement}
		class="modal fixed inset-0 bg-black text-white w-full h-screen flex flex-col z-9999 overflow-hidden overscroll-contain"
	>
		<div
			class="shrink-0 h-14 px-2 flex items-center justify-between select-none relative z-20 bg-black border-b border-white/10"
		>
			<button
				type="button"
				class="p-3 rounded-md hover:bg-white/10"
				aria-label="Close"
				on:pointerdown={(e) => {
					e.stopImmediatePropagation();
					e.preventDefault();
					show = false;
				}}
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

			<button
				type="button"
				class="p-3 rounded-md hover:bg-white/10"
				aria-label="Download"
				on:pointerdown={(e) => {
					e.stopImmediatePropagation();
					e.preventDefault();
				}}
				on:click={(e) => {
					e.stopPropagation();
					downloadImage(src, downloadBasename(alt, src));
				}}
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
		<div class="flex-1 min-h-0 w-full overflow-hidden">
			<div bind:this={sceneElement} class="flex h-full w-full justify-center items-center">
				<img
					{src}
					{alt}
					class="max-h-full max-w-full object-contain select-none"
					draggable="false"
				/>
			</div>
		</div>
	</div>
{/if}
