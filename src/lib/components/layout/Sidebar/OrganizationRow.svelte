<script lang="ts">
	import { DropdownMenu } from 'bits-ui';
	import { createEventDispatcher, getContext, onMount, tick } from 'svelte';
	import { activeOrganizationId, organizations, user } from '$lib/stores';
	import { flyAndScale } from '$lib/utils/transitions';
	import Check from '$lib/components/icons/Check.svelte';
	import ChevronDown from '$lib/components/icons/ChevronDown.svelte';

	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher();

	let open = false;

	// The same fallback as the user menu: the personal organization.
	$: current =
		($organizations ?? []).find((org) => org.id === $activeOrganizationId) ?? {
			id: $user?.id,
			name: 'Personal',
			kind: 'personal'
		};

	// A name that doesn't fit on one line at the row's text size drops to a
	// smaller size on two lines, so the row stays as tall as the rows around it.
	let nameBox: HTMLElement;
	let nameMeasure: HTMLElement;
	let twoLines = false;

	const fit = () => {
		if (nameBox && nameMeasure) twoLines = nameMeasure.scrollWidth > nameBox.clientWidth;
	};

	$: current.name, tick().then(fit);

	onMount(() => {
		const observer = new ResizeObserver(fit);
		observer.observe(nameBox);
		return () => observer.disconnect();
	});
</script>

<!-- Which organization the sidebar shows, and a switcher, so it is easy to find.
     Styled like the Workspace and Scheduled tasks rows above it; the user menu
     keeps its own switcher too. -->
<div class="px-1.5 flex justify-center text-gray-800 dark:text-gray-200">
	<DropdownMenu.Root bind:open closeFocus={false} typeahead={false}>
		<DropdownMenu.Trigger
			class="grow min-w-0 flex items-center space-x-3 rounded-lg px-2 py-[7px] text-left hover:bg-gray-100 dark:hover:bg-gray-900 transition"
			aria-label={$i18n.t('Switch organization')}
		>
			<div class="self-center shrink-0">
				<svg
					xmlns="http://www.w3.org/2000/svg"
					fill="none"
					viewBox="0 0 24 24"
					stroke-width="2"
					stroke="currentColor"
					class="size-[1.1rem]"
				>
					<path
						stroke-linecap="round"
						stroke-linejoin="round"
						d="M18 18.72a9.094 9.094 0 0 0 3.741-.479 3 3 0 0 0-4.682-2.72m.94 3.198.001.031c0 .225-.012.447-.037.666A11.944 11.944 0 0 1 12 21c-2.17 0-4.207-.576-5.963-1.584A6.062 6.062 0 0 1 6 18.719m12 0a5.971 5.971 0 0 0-.941-3.197m0 0A5.995 5.995 0 0 0 12 12.75a5.995 5.995 0 0 0-5.058 2.772m0 0a3 3 0 0 0-4.681 2.72 8.986 8.986 0 0 0 3.74.477m.94-3.197a5.971 5.971 0 0 0-.94 3.197M15 6.75a3 3 0 1 1-6 0 3 3 0 0 1 6 0Zm6 3a2.25 2.25 0 1 1-4.5 0 2.25 2.25 0 0 1 4.5 0Zm-13.5 0a2.25 2.25 0 1 1-4.5 0 2.25 2.25 0 0 1 4.5 0Z"
					/>
				</svg>
			</div>

			<!-- The text keeps a one-line height. Two smaller lines are centered on
			     it and spill into the row's padding. -->
			<div
				class="flex flex-1 min-w-0 h-5 gap-1.5 self-center translate-y-[0.5px] {twoLines
					? 'items-center'
					: 'items-baseline'}"
			>
				<span class="shrink-0 font-medium text-sm font-primary">{$i18n.t('Organization')}</span>
				<div bind:this={nameBox} class="relative flex flex-1 min-w-0 h-5 items-center">
					<span
						class="min-w-0 text-gray-500 dark:text-gray-400 {twoLines
							? 'line-clamp-2 break-words text-[11px] leading-[13px]'
							: 'truncate text-sm'}">{current.name}</span
					>
					<span
						bind:this={nameMeasure}
						aria-hidden="true"
						class="invisible absolute left-0 top-0 w-0 overflow-hidden whitespace-nowrap text-sm"
						>{current.name}</span
					>
				</div>
			</div>

			<ChevronDown
				className="size-3.5 shrink-0 self-center text-gray-400 transition {open ? 'rotate-180' : ''}"
				strokeWidth="2.5"
			/>
		</DropdownMenu.Trigger>

		<DropdownMenu.Content
			class="w-60 max-h-72 overflow-y-auto rounded-xl px-1 py-1.5 z-50 bg-white dark:bg-gray-850 dark:text-white shadow-lg"
			sideOffset={4}
			side="bottom"
			align="start"
			transition={flyAndScale}
		>
			{#each $organizations ?? [] as org (org.id)}
				<DropdownMenu.Item
					class="flex items-center gap-2 rounded-md px-3 py-1.5 text-sm cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800 {org.id ===
					$activeOrganizationId
						? 'font-medium'
						: 'text-gray-600 dark:text-gray-300'}"
					on:click={() => {
						if (org.id !== $activeOrganizationId) dispatch('switch-org', org.id);
					}}
				>
					{#if org.logo}
						<img src={org.logo} alt="" class="size-5 rounded-full object-cover shrink-0" />
					{/if}
					<span class="truncate flex-1">{org.name}</span>
					{#if org.id === $activeOrganizationId}
						<Check className="size-4 shrink-0" strokeWidth="2.5" />
					{/if}
				</DropdownMenu.Item>
			{/each}
		</DropdownMenu.Content>
	</DropdownMenu.Root>
</div>
