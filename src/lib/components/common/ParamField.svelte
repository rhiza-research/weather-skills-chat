<script lang="ts">
	import { getContext } from 'svelte';

	import Switch from './Switch.svelte';
	import SettingToggle from './SettingToggle.svelte';

	const i18n = getContext('i18n');

	export let label = '';
	export let tooltip = '';
	export let value: any = null;
	export let start: any = '';
	export let type: 'text' | 'number' | 'range' | 'switch' = 'text';
	export let placeholder = '';
	export let min: number | undefined = undefined;
	export let max: number | undefined = undefined;
	export let step: number | 'any' = 'any';

	$: custom = (value ?? null) !== null;
</script>

<div>
	<SettingToggle
		{label}
		{tooltip}
		text={custom ? $i18n.t('Custom') : $i18n.t('Default')}
		on:click={() => (value = custom ? null : start)}
	/>

	{#if custom}
		<div class="flex mt-0.5 space-x-2">
			{#if type === 'range'}
				<input
					class="flex-1 h-2 self-center rounded-lg cursor-pointer accent-black dark:accent-white"
					type="range"
					{min}
					{max}
					{step}
					bind:value
				/>
				<input class="bg-transparent text-center w-14" type="number" {min} {max} bind:value />
			{:else if type === 'number'}
				<input class="field" type="number" {min} {max} {placeholder} bind:value />
			{:else if type === 'switch'}
				<div class="flex flex-1 justify-between items-center pr-2">
					<div class="text-xs text-gray-500">{value ? 'Enabled' : 'Disabled'}</div>
					<Switch bind:state={value} />
				</div>
			{:else}
				<input class="field" type="text" {placeholder} autocomplete="off" bind:value />
			{/if}
		</div>
	{/if}
</div>
