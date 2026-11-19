<script lang="ts">
	import Tooltip from './Tooltip.svelte';

	export let label = '';
	export let description = '';
	export let tooltip = '';
</script>

<Tooltip content={tooltip} placement="top-start" className="inline-tooltip">
	<div class="flex w-full justify-between py-1.5">
		<div class="self-center">
			<div class="field-label">{label}</div>
			{#if description}<div class="text-xs text-muted">{description}</div>{/if}
		</div>
		<slot />
	</div>
</Tooltip>
