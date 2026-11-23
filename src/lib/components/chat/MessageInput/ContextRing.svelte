<script lang="ts">
	import { getContext } from 'svelte';
	import { DropdownMenu } from 'bits-ui';
	import Dropdown from '$lib/components/common/Dropdown.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import { flyAndScale } from '$lib/utils/transitions';
	import { contextShown } from '$lib/utils/compaction';
	import { isReplyRunning } from '$lib/utils/generationLiveness';

	const i18n = getContext('i18n');

	export let history;
	export let compacting = false;
	// Absent when the chat cannot be changed.
	export let onCompact: (() => void) | null = null;

	$: shown = contextShown(history);
	$: percent = shown ? Math.min(100, (shown.used / shown.window) * 100) : 0;
	$: current = history?.messages?.[history?.currentId];
	$: canCompact =
		!compacting &&
		current?.role === 'assistant' &&
		!isReplyRunning(current) &&
		current?.compaction?.status !== 'done';
</script>

{#if shown}
	<Dropdown>
		{#if compacting}
			<div class="mr-3" role="img" aria-label={$i18n.t('Compacting conversation')}>
				<Spinner className="size-[19.2px]" />
			</div>
		{:else}
			<!-- r = 100/2π so the circumference is 100 and the dash length is the percent -->
			<svg
				viewBox="0 0 36 36"
				class="block size-[19.2px] -rotate-90 mr-3"
				role="img"
				aria-label={$i18n.t('Context usage')}
			>
				<circle
					cx="18"
					cy="18"
					r="15.9155"
					fill="none"
					stroke-width="4"
					class="stroke-gray-200 dark:stroke-gray-700"
				/>
				<circle
					cx="18"
					cy="18"
					r="15.9155"
					fill="none"
					stroke-width="4"
					stroke-dasharray="{percent} 100"
					class="stroke-gray-600 dark:stroke-gray-300"
				/>
			</svg>
		{/if}

		<div slot="content">
			<DropdownMenu.Content
				class="rounded-xl px-3 py-2 border border-gray-300/30 dark:border-gray-700/50 z-50 bg-white dark:bg-gray-850 dark:text-white shadow-sm text-sm"
				sideOffset={10}
				side="bottom"
				align="end"
				transition={flyAndScale}
			>
				<div class="font-medium">{$i18n.t('Context usage')}</div>
				<div class="mt-1 tabular-nums">
					{shown.estimate
						? $i18n.t('~{{used}} of {{total}} tokens (estimate)', {
								used: shown.used.toLocaleString(),
								total: shown.window.toLocaleString()
							})
						: $i18n.t('{{used}} of {{total}} tokens', {
								used: shown.used.toLocaleString(),
								total: shown.window.toLocaleString()
							})}
				</div>
				<div class="text-gray-500 dark:text-gray-400 tabular-nums">
					{$i18n.t('{{percent}}% used', { percent: percent.toFixed(1) })}
				</div>
				{#if onCompact}
					<button
						type="button"
						class="mt-2 w-full px-2.5 py-1.5 text-sm font-medium rounded-full border border-gray-200 dark:border-gray-700 text-gray-700 dark:text-gray-200 shadow-sm hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors disabled:cursor-not-allowed disabled:opacity-50 disabled:shadow-none disabled:hover:bg-transparent"
						disabled={!canCompact}
						on:click={() => onCompact?.()}
					>
						{compacting ? $i18n.t('Compacting…') : $i18n.t('Compact now')}
					</button>
				{/if}
			</DropdownMenu.Content>
		</div>
	</Dropdown>
{/if}
