<script lang="ts">
	import { getContext } from 'svelte';

	import Info from '$lib/components/icons/Info.svelte';
	import CreditRequestModal from '$lib/components/chat/Messages/CreditRequestModal.svelte';
	import { feedbackDraft } from '$lib/stores';
	import { isUsageLimitMessage } from '$lib/utils/usage';

	const i18n = getContext('i18n');

	export let content = '';

	let showCreditRequest = false;

	$: usageLimit = isUsageLimitMessage(content);
</script>

<div class="flex my-2 gap-2.5 border px-4 py-3 border-red-600/10 bg-red-600/10 rounded-lg">
	<div class=" self-start mt-0.5">
		<Info className="size-5 text-red-700 dark:text-red-400" />
	</div>

	<div class="flex flex-col gap-1">
		<div class=" self-start text-sm">
			{typeof content === 'string' ? content : JSON.stringify(content)}
		</div>

		{#if usageLimit}
			<button
				class="self-start mt-1 px-3 py-1 text-xs font-medium bg-black hover:bg-gray-900 text-white dark:bg-white dark:text-black dark:hover:bg-gray-100 transition rounded-full"
				type="button"
				on:click={() => {
					showCreditRequest = true;
				}}
			>
				{$i18n.t('Request credit increase')}
			</button>
		{:else}
			<div class="text-xs text-gray-600 dark:text-gray-400">
				{$i18n.t('If this keeps happening, please let us know by filling out the')}
				<button
					type="button"
					class="underline font-medium hover:text-gray-900 dark:hover:text-gray-200"
					on:click={() => {
						const text = typeof content === 'string' ? content : JSON.stringify(content);
						feedbackDraft.set({ description: `Error: ${text}\n\n` });
					}}
				>
					{$i18n.t('feedback form')}</button
				>.
			</div>
		{/if}
	</div>
</div>

{#if usageLimit}
	<CreditRequestModal bind:show={showCreditRequest} />
{/if}
