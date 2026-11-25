<script lang="ts">
	import ArrowUpRightSolid from '$lib/components/icons/ArrowUpRightSolid.svelte';
	import ChevronDown from '$lib/components/icons/ChevronDown.svelte';
	import ChevronUp from '$lib/components/icons/ChevronUp.svelte';
	import MagnifyingGlass from '$lib/components/icons/MagnifyingGlass.svelte';
	import Collapsible from '$lib/components/common/Collapsible.svelte';
	import { safeLinkUrl } from '$lib/utils';

	export let status = { urls: [], query: '' };
	let state = false;
</script>

<Collapsible bind:open={state} className="w-full space-y-1">
	<div
		class="flex items-center gap-2 text-muted hover:text-gray-700 dark:hover:text-gray-300 transition"
	>
		<slot />

		{#if state}
			<ChevronUp strokeWidth="3.5" className="size-3.5 " />
		{:else}
			<ChevronDown strokeWidth="3.5" className="size-3.5 " />
		{/if}
	</div>
	<div
		class="text-sm border border-line rounded-xl mb-1.5"
		slot="content"
	>
		{#if status?.query}
			<a
				href="https://www.google.com/search?q={status.query}"
				target="_blank"
				class="flex w-full items-center p-3 px-4 border-b border-line group/item justify-between font-normal text-gray-800 dark:text-gray-300 no-underline"
			>
				<div class="flex gap-2 items-center">
					<MagnifyingGlass />

					<div class=" line-clamp-1">
						{status.query}
					</div>
				</div>

				<div
					class="ml-1 text-on-inverse group-hover/item:text-gray-600 dark:group-hover/item:text-white transition"
				>
					<!--  -->
					<ArrowUpRightSolid className="size-4" />
				</div>
			</a>
		{/if}

		{#each status.urls as url, urlIdx}
			<a
				href={safeLinkUrl(url)}
				target="_blank"
				class="flex w-full items-center p-3 px-4 {urlIdx === status.urls.length - 1
					? ''
					: 'border-b border-line'} group/item justify-between font-normal text-gray-800 dark:text-gray-300"
			>
				<div class=" line-clamp-1">
					{url}
				</div>

				<div
					class="ml-1 text-on-inverse group-hover/item:text-gray-600 dark:group-hover/item:text-white transition"
				>
					<!--  -->
					<ArrowUpRightSolid className="size-4" />
				</div>
			</a>
		{/each}
	</div>
</Collapsible>
