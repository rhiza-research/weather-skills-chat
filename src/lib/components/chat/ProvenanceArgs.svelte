<script lang="ts">
	import { getContext } from 'svelte';
	import { argRows } from '$lib/chat/provenanceGraph';

	const i18n = getContext('i18n');

	export let args: unknown;
</script>

<!-- One row per argument, laid out like the chat's arguments viewer; long values scroll. -->
{#each argRows(args) as row}
	<div data-row class="mt-0.5 {row.multiline ? '' : 'flex items-baseline gap-x-2'}">
		<span class="shrink-0 font-mono text-xs font-semibold text-gray-900 dark:text-gray-100"
			>{row.key}</span
		>
		{#if row.multiline}
			<!-- svelte-ignore a11y-no-noninteractive-tabindex: focusable so the keyboard can scroll it -->
			<pre
				class="m-0 mt-0.5 mb-1 max-h-[150px] overflow-auto rounded-lg border border-gray-100 dark:border-gray-800 bg-gray-50 dark:bg-gray-900 px-2 py-1.5 font-mono text-xs leading-[1.45] text-gray-800 dark:text-gray-200"
				tabindex="0">{row.value}</pre>
		{:else}
			<span
				class="min-w-0 flex-1 whitespace-pre-wrap break-words font-mono text-xs text-gray-600 dark:text-gray-300"
				>{row.value}</span
			>
		{/if}
	</div>
{:else}
	<div data-row class="mt-0.5 text-gray-500">{$i18n.t('No arguments.')}</div>
{/each}
