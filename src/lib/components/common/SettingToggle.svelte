<script lang="ts">
	import { createEventDispatcher } from 'svelte';
	import SettingRow from './SettingRow.svelte';
	import Switch from './Switch.svelte';

	const dispatch = createEventDispatcher();

	export let label = '';
	export let tooltip = '';
	export let text = '';
	export let checked: boolean | undefined = undefined;
</script>

<SettingRow {label} {tooltip}>
	{#if checked !== undefined}
		<Switch state={checked} on:change={(e) => e.detail !== checked && dispatch('click')} />
	{:else}
		<button class="btn-secondary" type="button" aria-label="{label}: {text}" on:click>{text}</button>
	{/if}
</SettingRow>
