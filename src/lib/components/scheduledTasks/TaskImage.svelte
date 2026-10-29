<script lang="ts">
	import { getAutomationImageUrl } from '$lib/apis/automations';

	/** A task with id, name, and image_updated_at. */
	export let task;
	export let className = 'size-10 rounded-lg';

	let failed = false;
	$: src = task?.image_updated_at ? getAutomationImageUrl(task.id, task.image_updated_at) : null;
	$: if (src) failed = false;
</script>

{#if src && !failed}
	<img
		{src}
		alt=""
		class="{className} shrink-0 object-cover bg-gray-100 dark:bg-gray-850"
		loading="lazy"
		on:error={() => (failed = true)}
	/>
{:else}
	<div
		class="{className} shrink-0 flex items-center justify-center bg-gray-100 dark:bg-gray-850 text-gray-500 dark:text-gray-400 font-medium uppercase select-none"
		aria-hidden="true"
	>
		{(task?.name ?? '?').trim().charAt(0) || '?'}
	</div>
{/if}
