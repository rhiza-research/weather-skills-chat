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
     The user menu keeps its own switcher too. -->
<div class="px-2 mb-2">
	<DropdownMenu.Root bind:open closeFocus={false} typeahead={false}>
		<DropdownMenu.Trigger
			class="w-full flex items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-gray-100 dark:hover:bg-gray-900 transition"
			aria-label={$i18n.t('Switch organization')}
		>
			<div class="flex-1 min-w-0">
				<div class="text-[11px] uppercase tracking-wide text-gray-400">
					{$i18n.t('Organization')}
				</div>
				<div class="flex items-center gap-2 min-w-0">
					{#if current.logo}
						<img src={current.logo} alt="" class="size-5 rounded-full object-cover shrink-0" />
					{/if}
					<div class="truncate text-sm font-semibold text-gray-800 dark:text-gray-100">
						{current.name}
					</div>
				</div>
			</div>
			<ChevronDown
				className="size-4 text-gray-400 shrink-0 transition {open ? 'rotate-180' : ''}"
				strokeWidth="2"
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
