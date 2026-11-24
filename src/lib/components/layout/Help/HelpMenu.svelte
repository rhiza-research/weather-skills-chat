<script lang="ts">
	import { DropdownMenu } from 'bits-ui';
	import { getContext } from 'svelte';

	import { feedbackDraft } from '$lib/stores';
	import { flyAndScale } from '$lib/utils/transitions';

	import Dropdown from '$lib/components/common/Dropdown.svelte';
	import QuestionMarkCircle from '$lib/components/icons/QuestionMarkCircle.svelte';
	import Lifebuoy from '$lib/components/icons/Lifebuoy.svelte';
	import Keyboard from '$lib/components/icons/Keyboard.svelte';
	const i18n = getContext('i18n');

	export let showDocsHandler: Function;
	export let showShortcutsHandler: Function;

	export let onClose: Function = () => {};
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
			class="menu-panel max-w-[200px]"
			sideOffset={4}
			side="top"
			align="end"
			transition={flyAndScale}
		>
			<DropdownMenu.Item
				class="menu-item"
				id="chat-help-email-button"
				on:click={() => {
					feedbackDraft.set({});
				}}
			>
				<QuestionMarkCircle className="size-5" />
				<div class="flex items-center">{$i18n.t('Contact support')}</div>
			</DropdownMenu.Item>

			<DropdownMenu.Item
				class="menu-item"
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
