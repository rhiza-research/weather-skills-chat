<script lang="ts">
	import { DropdownMenu } from 'bits-ui';
	import { createEventDispatcher, getContext } from 'svelte';
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
				{#if current.logo}
					<img src={current.logo} alt="" class="size-[1.1rem] rounded-full object-cover" />
				{:else}
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
							d="M2.25 21h19.5m-18-18v18m10.5-18v18m6-13.5V21M6.75 6.75h.75m-.75 3h.75m-.75 3h.75m3-6h.75m-.75 3h.75m-.75 3h.75M6.75 21v-3.375c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125V21M3 3h12m-.75 4.5H21m-3.75 3.75h.008v.008h-.008v-.008Zm0 3h.008v.008h-.008v-.008Zm0 3h.008v.008h-.008v-.008Z"
						/>
					</svg>
				{/if}
			</div>

			<div class="flex flex-1 min-w-0 items-baseline gap-1.5 self-center translate-y-[0.5px]">
				<span class="shrink-0 font-medium text-sm font-primary">{$i18n.t('Organization')}</span>
				<span class="truncate text-sm text-gray-500 dark:text-gray-400">{current.name}</span>
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
