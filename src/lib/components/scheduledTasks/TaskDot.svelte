<script lang="ts">
	import { getContext } from 'svelte';
	import type { TaskDot } from '$lib/utils/scheduledTasks';

	export let dot: TaskDot | null = null;

	const i18n = getContext('i18n');

	$: label = dot
		? {
				running: $i18n.t('Running'),
				success: $i18n.t('Succeeded'),
				failure: $i18n.t('Failed'),
				unknown: $i18n.t('Finished without a result'),
				error: $i18n.t('Error')
			}[dot]
		: '';
</script>

{#if dot}
	<span
		class="inline-block size-2 shrink-0 rounded-full {dot === 'running'
			? 'bg-gray-400 animate-pulse'
			: dot === 'success'
				? 'bg-green-500'
				: dot === 'failure'
					? 'bg-red-500'
					: dot === 'unknown'
						? 'bg-orange-400'
						: 'border-2 border-red-500'}"
		title={label}
		aria-label={label}
		role="img"
	/>
{/if}
