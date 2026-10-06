<script lang="ts">
	import { onDestroy } from 'svelte';

	export let placement = 'top';
	export let content = `I'm a tooltip!`;
	export let touch = true;
	export let className = 'flex';
	export let theme = '';
	export let offset = [0, 4];
	export let allowHTML = true;
	export let tippyOptions = {};

	let tooltipElement;
	let tooltipInstance;
	let active = false;
	let purify: { sanitize: (dirty: string) => string } | null = null;
	let tippyLib: ((element: Element, options: Record<string, unknown>) => { setContent: (value: string) => void; destroy: () => void }) | null = null;

	const plainText = (value: unknown) => `${value ?? ''}`.replace(/<[^>]*>/g, '');

	async function loadTippy() {
		if (!tippyLib) {
			const [mod] = await Promise.all([import('tippy.js'), import('tippy.js/dist/tippy.css')]);
			tippyLib = mod.default;
		}
		return tippyLib;
	}

	async function sanitize(value: string) {
		if (!purify) {
			purify = (await import('dompurify')).default;
		}
		return purify.sanitize(value);
	}

	$: if (tooltipElement && content && active) {
		const element = tooltipElement;
		const next = content;
		Promise.all([sanitize(next), loadTippy()]).then(([clean, tippy]) => {
			if (tooltipElement !== element || content !== next) {
				return;
			}
			if (tooltipInstance) {
				tooltipInstance.setContent(clean);
			} else {
				tooltipInstance = tippy(element, {
					content: clean,
					placement: placement,
					allowHTML: allowHTML,
					touch: touch,
					...(theme !== '' ? { theme } : { theme: 'dark' }),
					arrow: false,
					offset: offset,
					...tippyOptions
				});
			}
		});
	} else if (tooltipInstance && content === '') {
		if (tooltipInstance) {
			tooltipInstance.destroy();
		}
	}

	onDestroy(() => {
		if (tooltipInstance) {
			tooltipInstance.destroy();
		}
	});
</script>

<div
	bind:this={tooltipElement}
	aria-label={plainText(content)}
	class={className}
	on:pointerenter={() => (active = true)}
	on:focusin={() => (active = true)}
>
	<slot />
</div>
