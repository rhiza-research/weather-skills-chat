<script lang="ts">
	import { onMount, tick, getContext, type ComponentType } from 'svelte';

	const i18n = getContext('i18n');

	import Tooltip from '../common/Tooltip.svelte';
	import HelpMenu from './Help/HelpMenu.svelte';
	import { whenAppIdle } from '$lib/utils/idle';

	let showShortcuts = false;

	let ShortcutsModal: ComponentType | null = null;
	const loadShortcutsModal = () =>
		import('../chat/ShortcutsModal.svelte').then((m) => (ShortcutsModal = m.default));
	$: if (showShortcuts && !ShortcutsModal) loadShortcutsModal();
	whenAppIdle(loadShortcutsModal);
</script>

<div class=" hidden lg:flex fixed bottom-0 right-0 px-1 py-1 z-20">
	<button
		id="show-shortcuts-button"
		class="hidden"
		on:click={() => {
			showShortcuts = !showShortcuts;
		}}
	/>

	<HelpMenu
		showDocsHandler={() => {
			showShortcuts = !showShortcuts;
		}}
		showShortcutsHandler={() => {
			showShortcuts = !showShortcuts;
		}}
	>
		<Tooltip content={$i18n.t('Help')} placement="left">
			<button
				class="text-gray-600 dark:text-gray-300 bg-gray-300/20 size-4 flex items-center justify-center text-[0.7rem] rounded-full"
			>
				?
			</button>
		</Tooltip>
	</HelpMenu>
</div>

{#if ShortcutsModal}
	<svelte:component this={ShortcutsModal} bind:show={showShortcuts} />
{/if}
