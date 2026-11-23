<script lang="ts">
	import { getContext, onDestroy } from 'svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import ChevronDown from '$lib/components/icons/ChevronDown.svelte';
	import ChevronUp from '$lib/components/icons/ChevronUp.svelte';
	import {
		compactionExpiresAt,
		compactionRunning,
		type Compaction
	} from '$lib/utils/compaction';

	const i18n = getContext('i18n');

	export let compaction: Compaction;

	let open = false;
	let now = Date.now();
	let timer: ReturnType<typeof setTimeout> | null = null;

	// Re-check when a running compaction would count as failed.
	const recheckAtExpiry = (running: boolean) => {
		if (timer) clearTimeout(timer);
		timer = running
			? setTimeout(() => (now = Date.now()), compactionExpiresAt(compaction) - Date.now() + 50)
			: null;
	};

	$: running = compactionRunning(compaction, now);
	$: recheckAtExpiry(running);

	onDestroy(() => {
		if (timer) clearTimeout(timer);
	});
</script>

{#if running}
	<div
		class="flex items-center gap-2 mt-3 text-xs text-gray-500 dark:text-gray-400"
		role="status"
	>
		<Spinner className="size-3" />
		{$i18n.t('Compacting conversation… Sending is paused until it finishes.')}
	</div>
{:else if compaction?.status === 'done'}
	<div class="mt-3">
		<button
			type="button"
			class="flex w-full items-center gap-2 text-xs text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 transition"
			aria-expanded={open}
			on:click={() => (open = !open)}
		>
			<span class="flex-1 border-t border-gray-200 dark:border-gray-800" />
			<span>{$i18n.t('Chat compacted. The model sees a summary of the messages above.')}</span>
			{#if open}
				<ChevronUp className="size-3" />
			{:else}
				<ChevronDown className="size-3" />
			{/if}
			<span class="flex-1 border-t border-gray-200 dark:border-gray-800" />
		</button>
		{#if open}
			<div
				class="mt-2 rounded-xl bg-gray-50 dark:bg-gray-850 px-3 py-2 text-sm text-gray-700 dark:text-gray-300 whitespace-pre-wrap"
			>
				{compaction.summary}
			</div>
		{/if}
	</div>
{/if}
