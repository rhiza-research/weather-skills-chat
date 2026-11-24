<script lang="ts">
	import { getContext, onDestroy } from 'svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import ChevronDown from '$lib/components/icons/ChevronDown.svelte';
	import ChevronUp from '$lib/components/icons/ChevronUp.svelte';
	import { compactionRunning, compactionSteps, type Compaction } from '$lib/utils/compaction';

	const i18n = getContext('i18n');

	export let compaction: Compaction;

	let open = false;
	let now = Date.now();
	let ticker: ReturnType<typeof setInterval> | null = null;

	// Tick the timers each second while running; a tick also notices the timeout.
	const tick = (running: boolean) => {
		if (running && !ticker) ticker = setInterval(() => (now = Date.now()), 1000);
		if (!running && ticker) {
			clearInterval(ticker);
			ticker = null;
		}
	};

	$: running = compactionRunning(compaction, now);
	$: tick(running);
	$: steps = running ? compactionSteps(compaction, now) : [];

	const labels = {
		sending: 'Sending the conversation to the model',
		waiting: 'Waiting for the model',
		receiving: 'Receiving the summary'
	};
	const clock = (seconds: number) =>
		`${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;

	onDestroy(() => {
		if (ticker) clearInterval(ticker);
	});
</script>

{#if running}
	<div class="mt-3 text-xs text-gray-500 dark:text-gray-400" role="status">
		<div class="flex items-center gap-2">
			<Spinner className="size-3" />
			{$i18n.t('Compacting conversation… Sending is paused until it finishes.')}
		</div>
		<ul class="mt-1 ml-5 space-y-0.5">
			{#each steps as row}
				<li class="flex gap-2 {row.current ? '' : 'text-gray-400 dark:text-gray-500'}">
					<span>{row.step ? $i18n.t(labels[row.step]) : $i18n.t('Compacting')}</span>
					<span class="tabular-nums">{clock(row.seconds)}</span>
				</li>
			{/each}
		</ul>
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
