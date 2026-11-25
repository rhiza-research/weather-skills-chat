<script lang="ts">
	import { getContext, onDestroy } from 'svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import ChevronDown from '$lib/components/icons/ChevronDown.svelte';
	import ChevronUp from '$lib/components/icons/ChevronUp.svelte';
	import { compactionRunning, compactionStep, type Compaction } from '$lib/utils/compaction';

	const i18n = getContext('i18n');

	export let compaction: Compaction;

	let open = false;
	let now = Date.now();
	let ticker: ReturnType<typeof setInterval> | null = null;

	// Tick the timer each second while running; a tick also notices the timeout.
	const tick = (running: boolean) => {
		if (running && !ticker) ticker = setInterval(() => (now = Date.now()), 1000);
		if (!running && ticker) {
			clearInterval(ticker);
			ticker = null;
		}
	};

	$: running = compactionRunning(compaction, now);
	$: tick(running);
	$: current = compactionStep(compaction, now);

	const labels = {
		sending: 'Sending the conversation to the model',
		waiting: 'Waiting for the model',
		receiving: 'Receiving the summary'
	};
	// Same as the activity line's: 42s, 1m 5s.
	const elapsed = (seconds: number) =>
		seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`;

	onDestroy(() => {
		if (ticker) clearInterval(ticker);
	});
</script>

{#if running}
	<div class="mt-3 w-fit font-medium flex items-center gap-2 shimmer muted" role="status">
		<Spinner className="size-4" />
		<div class="text-base line-clamp-1">
			{current.step ? $i18n.t(labels[current.step]) : $i18n.t('Compacting conversation')}
			({elapsed(current.seconds)})…
		</div>
	</div>
{:else if compaction?.status === 'done'}
	<div class="mt-3">
		<button
			type="button"
			class="flex w-full items-center gap-2 text-xs muted hover:text-gray-700 dark:hover:text-gray-200 transition"
			aria-expanded={open}
			on:click={() => (open = !open)}
		>
			<span class="flex-1 border-t border-line-strong" />
			<span>{$i18n.t('Chat compacted. The model sees a summary of the messages above.')}</span>
			{#if open}
				<ChevronUp className="size-3" />
			{:else}
				<ChevronDown className="size-3" />
			{/if}
			<span class="flex-1 border-t border-line-strong" />
		</button>
		{#if open}
			<div
				class="mt-2 rounded-xl bg-surface px-3 py-2 text-sm body whitespace-pre-wrap"
			>
				{compaction.summary}
			</div>
		{/if}
	</div>
{/if}
