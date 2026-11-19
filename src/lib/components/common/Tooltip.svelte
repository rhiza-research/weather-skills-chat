<script lang="ts">
	import { afterUpdate, onDestroy, onMount } from 'svelte';

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
	let hovering = false;
	let active = false;
	let purify: { sanitize: (dirty: string) => string } | null = null;
	let tippyLib: ((element: Element, options: Record<string, unknown>) => { setContent: (value: string) => void; destroy: () => void }) | null = null;

	const plainText = (value: unknown) => `${value ?? ''}`.replace(/<[^>]*>/g, '');

	// Name the nested control (icon buttons have no text) instead of labelling the wrapper div.
	const nameControl = () => {
		const el = tooltipElement?.querySelector('button, a[href], [role="button"], [role="switch"]');
		if (el && !el.textContent?.trim() && !el.hasAttribute('aria-label') && !el.hasAttribute('aria-labelledby')) {
			el.setAttribute('aria-label', plainText(content));
		}
	};
	onMount(nameControl);
	afterUpdate(nameControl);

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
					...tippyOptions,
					// The instance is made on the first hover, after tippy's own hover
					// handler would have run: show it now if the pointer is still here,
					// or the first hover over anything shows no tooltip.
					showOnCreate: hovering && tippyOptions.showOnCreate !== false
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
	class={className}
	on:pointerenter={() => (active = hovering = true)}
	on:pointerleave={() => (hovering = false)}
	on:focusin={() => (active = true)}
>
	<slot />
</div>
