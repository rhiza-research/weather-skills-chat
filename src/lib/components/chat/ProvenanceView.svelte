<script lang="ts">
	import { getContext } from 'svelte';
	import ProvenanceGraph from './ProvenanceGraph.svelte';
	import ProvenanceSteps from './ProvenanceSteps.svelte';
	import ProvenanceTree from './ProvenanceTree.svelte';
	import ArrowsPointingOut from '../icons/ArrowsPointingOut.svelte';
	import XMark from '../icons/XMark.svelte';
	import Tooltip from '../common/Tooltip.svelte';

	const i18n = getContext('i18n');

	/** Full provenance branches, with their steps. */
	export let branches: Array<any> = [];
	export let fileName = '';
	export let title = '';
	export let fill = false;
	export let maxHeight = 220;
	export let mode: 'graph' | 'text' = 'graph';
	export let fullscreen = false;
	// Off where the host has its own full-screen button, and inside full screen.
	export let fullscreenButton = true;

	const iconButton =
		'p-1 rounded-md text-gray-500 hover:text-gray-800 dark:hover:text-gray-200 hover:bg-black/5 dark:hover:bg-white/5';
	const modes = [
		['graph', 'Graph'],
		['text', 'Text']
	] as const;

	const portal = (node: HTMLElement) => {
		document.body.appendChild(node);
		return { destroy: () => node.remove() };
	};

	const onKey = (e: KeyboardEvent) => {
		if (fullscreen && e.key === 'Escape') fullscreen = false;
	};
</script>

<svelte:window on:keydown={onKey} />

<div class="flex flex-col min-w-0 {fill ? 'h-full min-h-0' : ''}">
	{#if mode === 'graph'}
		<ProvenanceGraph {branches} {fileName} {fill} {maxHeight}>
			<div slot="lead" class="flex rounded-md bg-gray-100 dark:bg-gray-800 p-0.5 text-xs">
				{#each modes as [value, label]}
					<button
						type="button"
						class="px-2 py-0.5 rounded {mode === value
							? 'bg-white dark:bg-gray-700 text-gray-800 dark:text-gray-100 shadow-sm'
							: 'text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'}"
						aria-pressed={mode === value}
						on:click={() => (mode = value)}>{$i18n.t(label)}</button
					>
				{/each}
			</div>
			<svelte:fragment slot="trail">
				{#if fullscreenButton}
					<Tooltip content={$i18n.t('Open in full screen')}>
						<button
							type="button"
							class={iconButton}
							aria-label={$i18n.t('Open in full screen')}
							on:click={() => (fullscreen = true)}
						>
							<ArrowsPointingOut className="size-3.5" />
						</button>
					</Tooltip>
				{/if}
			</svelte:fragment>
		</ProvenanceGraph>
	{:else}
		<div class="flex items-center justify-between gap-2 mb-1 min-h-5">
			<div class="flex rounded-md bg-gray-100 dark:bg-gray-800 p-0.5 text-xs">
				{#each modes as [value, label]}
					<button
						type="button"
						class="px-2 py-0.5 rounded {mode === value
							? 'bg-white dark:bg-gray-700 text-gray-800 dark:text-gray-100 shadow-sm'
							: 'text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'}"
						aria-pressed={mode === value}
						on:click={() => (mode = value)}>{$i18n.t(label)}</button
					>
				{/each}
			</div>
			{#if fullscreenButton}
				<Tooltip content={$i18n.t('Open in full screen')}>
					<button
						type="button"
						class={iconButton}
						aria-label={$i18n.t('Open in full screen')}
						on:click={() => (fullscreen = true)}
					>
						<ArrowsPointingOut className="size-3.5" />
					</button>
				</Tooltip>
			{/if}
		</div>
		<div class="overflow-y-auto {fill ? 'flex-1 min-h-0' : 'max-h-80'}">
			{#if branches.length === 1}
				<ProvenanceSteps steps={branches[0]?.steps ?? []} />
			{:else}
				<ProvenanceTree {branches} />
			{/if}
		</div>
	{/if}
</div>

{#if fullscreen}
	<div
		use:portal
		class="fixed inset-0 z-[9999] flex flex-col bg-white dark:bg-gray-900 px-4 pb-4"
		role="dialog"
		aria-modal="true"
		aria-label={$i18n.t('Provenance')}
	>
		<div class="flex items-center justify-between gap-2 h-12 shrink-0">
			<div class="text-sm text-gray-600 dark:text-gray-300 truncate min-w-0">
				{title || fileName}
			</div>
			<button
				type="button"
				class={iconButton}
				aria-label={$i18n.t('Close')}
				on:click={() => (fullscreen = false)}
			>
				<XMark className="size-4" />
			</button>
		</div>
		<div class="flex-1 min-h-0">
			<svelte:self {branches} {fileName} fill bind:mode fullscreenButton={false} />
		</div>
	</div>
{/if}
