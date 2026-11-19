<script lang="ts">
	import ArrowDownTrayMini from '$lib/components/icons/ArrowDownTrayMini.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';
	import { onDestroy, onMount, getContext } from 'svelte';
	import panzoom, { type PanZoom } from 'panzoom';

	const i18n = getContext('i18n');

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
				class="p-3 rounded-xl hover:bg-white/10"
				aria-label={$i18n.t('Close')}
				on:pointerdown={(e) => {
					e.stopImmediatePropagation();
					e.preventDefault();
					show = false;
				}}
				on:click={() => {
					show = false;
				}}
			>
				<XMark className="size-6" />
			</button>

			<button
				type="button"
				class="p-3 rounded-xl hover:bg-white/10"
				aria-label={$i18n.t('Download')}
				on:pointerdown={(e) => {
					e.stopImmediatePropagation();
					e.preventDefault();
				}}
				on:click={(e) => {
					e.stopPropagation();
					downloadImage(src, downloadBasename(alt, src));
				}}
			>
				<ArrowDownTrayMini className="size-6" />
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
