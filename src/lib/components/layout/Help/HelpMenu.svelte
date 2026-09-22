<script lang="ts">
	import { DropdownMenu } from 'bits-ui';
	import { getContext } from 'svelte';

	import { config, showSettings } from '$lib/stores';
	import { helpEmailAddress } from '$lib/constants';
	import { flyAndScale } from '$lib/utils/transitions';

	import Dropdown from '$lib/components/common/Dropdown.svelte';
	import QuestionMarkCircle from '$lib/components/icons/QuestionMarkCircle.svelte';
	import Lifebuoy from '$lib/components/icons/Lifebuoy.svelte';
	import Keyboard from '$lib/components/icons/Keyboard.svelte';
	const i18n = getContext('i18n');

	export let showDocsHandler: Function;
	export let showShortcutsHandler: Function;

	export let onClose: Function = () => {};

	$: helpEmail = helpEmailAddress($config?.help_email);
</script>

<Dropdown
	on:change={(e) => {
		if (e.detail === false) {
			onClose();
		}
	}}
>
	<slot />

	<div slot="content">
		<DropdownMenu.Content
			class="w-full max-w-[200px] rounded-xl px-1 py-1.5 border border-gray-300/30 dark:border-gray-700/50 z-50 bg-white dark:bg-gray-850 dark:text-white shadow-lg"
			sideOffset={4}
			side="top"
			align="end"
			transition={flyAndScale}
		>
			<DropdownMenu.Item
				class="flex gap-2 items-center px-3 py-2 text-sm  cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800 rounded-md"
				id="chat-help-email-button"
				on:click={() => {
					window.location.href = `mailto:${helpEmail}`;
				}}
			>
				<QuestionMarkCircle className="size-5" />
				<div class="flex items-center">{$i18n.t('Contact support')}</div>
			</DropdownMenu.Item>

			<DropdownMenu.Item
				class="flex gap-2 items-center px-3 py-2 text-sm  cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800 rounded-md"
				id="chat-share-button"
				on:click={() => {
					showShortcutsHandler();
				}}
			>
				<Keyboard className="size-5" />
				<div class="flex items-center">{$i18n.t('Keyboard shortcuts')}</div>
			</DropdownMenu.Item>
		</DropdownMenu.Content>
	</div>
</Dropdown>
