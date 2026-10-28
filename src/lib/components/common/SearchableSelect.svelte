<script lang="ts">
	import { DropdownMenu } from 'bits-ui';
	import { createEventDispatcher, tick } from 'svelte';

	import { flyAndScale } from '$lib/utils/transitions';
	import { matchesSearch, type SelectItem } from '$lib/utils/modelFallback';
	import ChevronDown from '../icons/ChevronDown.svelte';
	import Check from '../icons/Check.svelte';
	import Search from '../icons/Search.svelte';

	const dispatch = createEventDispatcher();

	export let value: string | null = null;
	export let items: SelectItem[] = [];
	export let placeholder = '';
	export let searchPlaceholder = 'Search';
	export let noResults = 'No results found';
	export let disabled = false;

	let show = false;
	let searchValue = '';
	let highlighted = 0;
	let listElement: HTMLDivElement;

	$: selected = items.find((item) => item.value === value);
	$: filteredItems = items.filter((item) => matchesSearch(item.label, searchValue));

	const choose = (item: SelectItem) => {
		show = false;
		if (item.value !== value) {
			value = item.value;
			dispatch('change', item.value);
		}
	};

	const scrollToHighlighted = async () => {
		await tick();
		listElement
			?.querySelector('[data-highlighted-item="true"]')
			?.scrollIntoView({ block: 'nearest', behavior: 'instant' });
	};
</script>

<DropdownMenu.Root
	bind:open={show}
	onOpenChange={async (open) => {
		searchValue = '';
		highlighted = Math.max(
			0,
			items.findIndex((item) => item.value === value)
		);
		if (open) {
			await tick();
			listElement?.parentElement?.querySelector('input')?.focus();
			scrollToHighlighted();
		}
	}}
	closeFocus={false}
>
	<DropdownMenu.Trigger class="relative w-full text-left" {disabled} aria-label={placeholder}>
		<div
			class="flex w-full justify-between items-center text-sm bg-transparent outline-hidden {disabled
				? 'opacity-50'
				: ''}"
		>
			<span class="truncate">{selected?.label ?? placeholder}</span>
			<ChevronDown className="self-center ml-2 size-3 shrink-0" strokeWidth="2.5" />
		</div>
	</DropdownMenu.Trigger>

	<DropdownMenu.Content
		class="z-40 min-w-64 max-w-[calc(100vw-1rem)] rounded-xl bg-white dark:bg-gray-850 dark:text-white shadow-lg outline-hidden"
		transition={flyAndScale}
		side="bottom"
		align="start"
		sameWidth
		sideOffset={3}
	>
		<div class="flex items-center gap-2.5 px-4 mt-3 mb-1.5">
			<Search className="size-4" strokeWidth="2.5" />
			<input
				bind:value={searchValue}
				class="w-full text-sm bg-transparent outline-hidden"
				placeholder={searchPlaceholder}
				autocomplete="off"
				on:input={() => {
					highlighted = 0;
				}}
				on:keydown={(e) => {
					if (e.key === 'Enter') {
						e.preventDefault();
						if (filteredItems[highlighted]) {
							choose(filteredItems[highlighted]);
						}
					} else if (e.key === 'ArrowDown') {
						e.preventDefault();
						highlighted = Math.min(highlighted + 1, filteredItems.length - 1);
						scrollToHighlighted();
					} else if (e.key === 'ArrowUp') {
						e.preventDefault();
						highlighted = Math.max(highlighted - 1, 0);
						scrollToHighlighted();
					}
					// Keep the menu's own typeahead from taking the keystroke.
					e.stopPropagation();
				}}
			/>
		</div>

		<div class="px-2 my-2 max-h-80 overflow-y-auto" bind:this={listElement}>
			{#each filteredItems as item, index (item.value)}
				<button
					type="button"
					class="flex w-full text-left items-center rounded-lg py-1.5 pl-3 pr-1.5 text-sm text-gray-700 dark:text-gray-100 hover:bg-gray-100 dark:hover:bg-gray-800 {index ===
					highlighted
						? 'bg-gray-100 dark:bg-gray-800'
						: ''}"
					data-highlighted-item={index === highlighted}
					on:click={() => choose(item)}
					on:mousemove={() => {
						highlighted = index;
					}}
				>
					<span class="truncate">{item.label}</span>
					{#if item.value === value}
						<Check className="ml-auto size-3.5 shrink-0" />
					{/if}
				</button>
			{:else}
				<div class="px-3 py-2 text-sm text-gray-500">{noResults}</div>
			{/each}
		</div>
	</DropdownMenu.Content>
</DropdownMenu.Root>
