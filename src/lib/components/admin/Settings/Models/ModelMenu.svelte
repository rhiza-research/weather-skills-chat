<script lang="ts">
	import EyeSlash from '$lib/components/icons/EyeSlash.svelte';
	import Eye from '$lib/components/icons/Eye.svelte';
	import { DropdownMenu } from 'bits-ui';
	import { flyAndScale } from '$lib/utils/transitions';
	import { getContext } from 'svelte';

	import Dropdown from '$lib/components/common/Dropdown.svelte';
	import GarbageBin from '$lib/components/icons/GarbageBin.svelte';
	import Pencil from '$lib/components/icons/Pencil.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Tags from '$lib/components/chat/Tags.svelte';
	import Share from '$lib/components/icons/Share.svelte';
	import ArchiveBox from '$lib/components/icons/ArchiveBox.svelte';
	import DocumentDuplicate from '$lib/components/icons/DocumentDuplicate.svelte';
	import ArrowDownTray from '$lib/components/icons/ArrowDownTray.svelte';
	import ArrowUpCircle from '$lib/components/icons/ArrowUpCircle.svelte';

	import { config } from '$lib/stores';

	const i18n = getContext('i18n');

	export let user;
	export let model;

	export let exportHandler: Function;
	export let hideHandler: Function;

	export let onClose: Function;

	let show = false;
</script>

<Dropdown
	bind:show
	on:change={(e) => {
		if (e.detail === false) {
			onClose();
		}
	}}
>
	<Tooltip content={$i18n.t('More')}>
		<slot />
	</Tooltip>

	<div slot="content">
		<DropdownMenu.Content
			class="w-full max-w-[160px] rounded-xl px-1 py-1.5 border border-gray-300/30 dark:border-gray-700/50 z-50 bg-white dark:bg-gray-850 dark:text-white shadow-lg"
			sideOffset={-2}
			side="bottom"
			align="start"
			transition={flyAndScale}
		>
			<DropdownMenu.Item
				class="menu-item"
				on:click={() => {
					hideHandler();
				}}
			>
				{#if model?.meta?.hidden ?? false}
					<EyeSlash className="size-4" />
				{:else}
					<Eye className="size-4" />
				{/if}

				<div class="flex items-center">
					{#if model?.meta?.hidden ?? false}
						{$i18n.t('Show Model')}
					{:else}
						{$i18n.t('Hide Model')}
					{/if}
				</div>
			</DropdownMenu.Item>

			<DropdownMenu.Item
				class="menu-item"
				on:click={() => {
					exportHandler();
				}}
			>
				<ArrowDownTray />

				<div class="flex items-center">{$i18n.t('Export')}</div>
			</DropdownMenu.Item>
		</DropdownMenu.Content>
	</div>
</Dropdown>
