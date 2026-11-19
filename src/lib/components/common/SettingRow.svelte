<script lang="ts">
	import Tooltip from './Tooltip.svelte';

	export let label = '';
	export let tooltip = '';
</script>

<Tooltip content={tooltip} placement="top-start" className="inline-tooltip">
	<div class="flex w-full justify-between py-0.5">
		<div class="self-center field-label">{label}</div>
		<slot />
	</div>
</Tooltip>
