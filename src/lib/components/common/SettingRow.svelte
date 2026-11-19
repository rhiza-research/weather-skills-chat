<script lang="ts">
	import { onMount } from 'svelte';
	import Tooltip from './Tooltip.svelte';

	export let label = '';
	export let description = '';
	export let tooltip = '';

	const id = `setting-${Math.random().toString(36).slice(2, 8)}`;
	let row: HTMLElement;

	onMount(() => {
		row.querySelectorAll('select, textarea, input:not([type="hidden"]), [role="switch"]').forEach((el) => {
			if (!el.hasAttribute('aria-label') && !el.hasAttribute('aria-labelledby') && !(el as HTMLInputElement).labels?.length) {
				el.setAttribute('aria-labelledby', id);
			}
		});
	});
</script>

<Tooltip content={tooltip} placement="top-start" className="inline-tooltip">
	<div bind:this={row} class="flex w-full justify-between py-1.5">
		<div class="self-center">
			<div {id} class="text-xs font-medium">{label}</div>
			{#if description}<div class="text-xs text-muted">{description}</div>{/if}
		</div>
		<slot />
	</div>
</Tooltip>
