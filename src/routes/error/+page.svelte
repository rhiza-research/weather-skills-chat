<script>
	import { goto } from '$app/navigation';
	import { WEBUI_NAME, config } from '$lib/stores';
	import { onMount, getContext } from 'svelte';
	import HelpContact from '$lib/components/common/HelpContact.svelte';

	const i18n = getContext('i18n');

	let loaded = false;

	onMount(async () => {
		if ($config) {
			await goto('/');
		}

		loaded = true;
	});
</script>

{#if loaded}
	<div class="absolute w-full h-full flex z-50">
		<div class="absolute rounded-xl w-full h-full backdrop-blur-sm flex justify-center">
			<div class="m-auto pb-44 flex flex-col justify-center">
				<div class="max-w-md">
					<div class="text-center text-2xl font-medium z-50">
						{$i18n.t("{{webUIName}} isn't responding", { webUIName: $WEBUI_NAME })}
					</div>

					<div class=" mt-4 text-center text-sm w-full">
						{$i18n.t(
							'We could not reach the server. Please check your connection and try again in a moment.'
						)}
					</div>

					<div class=" mt-6 mx-auto relative group w-fit">
						<button
							class="relative z-20 flex px-5 py-2 rounded-full bg-gray-100 hover:bg-gray-200 transition font-medium text-sm"
							on:click={() => {
								location.href = '/';
							}}
						>
							{$i18n.t('Check Again')}
						</button>
					</div>

					<HelpContact
						className="mt-6 text-center text-xs text-gray-500 dark:text-gray-400"
						label={$i18n.t('Still stuck? Contact')}
					/>
				</div>
			</div>
		</div>
	</div>
{/if}
