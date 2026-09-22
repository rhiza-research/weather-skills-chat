<script lang="ts">
	import { getAdminDetails } from '$lib/apis/auths';
	import { onMount, getContext } from 'svelte';
	import { WEBUI_NAME } from '$lib/stores';
	import HelpContact from '$lib/components/common/HelpContact.svelte';

	const i18n = getContext('i18n');

	let adminDetails = null;

	onMount(async () => {
		adminDetails = await getAdminDetails(localStorage.token).catch((err) => {
			console.error(err);
			return null;
		});
	});
</script>

<div class="fixed w-full h-full flex z-999">
	<div
		class="absolute w-full h-full backdrop-blur-lg bg-white/10 dark:bg-gray-900/50 flex justify-center"
	>
		<div class="m-auto pb-10 flex flex-col justify-center">
			<div class="max-w-md">
				<div class="text-center dark:text-white text-2xl font-medium z-50">
					{$i18n.t('Account Activation Pending')}<br />
					{$i18n.t('Contact Admin for {{WEBUI_NAME}} Access', { WEBUI_NAME: $WEBUI_NAME })}
				</div>

				<div class=" mt-4 text-center text-sm dark:text-gray-200 w-full">
					{$i18n.t('Your account status is currently pending activation.')}<br />
					{$i18n.t(
						'To access {{WEBUI_NAME}}, please reach out to the administrator. Admins can manage user statuses from the Admin Panel.',
						{ WEBUI_NAME: $WEBUI_NAME }
					)}
				</div>

				{#if adminDetails}
					<div class="mt-4 text-sm font-medium text-center">
						<div>{$i18n.t('Admin')}: {adminDetails.name} ({adminDetails.email})</div>
					</div>
				{/if}

				<HelpContact
					className="mt-3 text-center text-xs text-gray-500 dark:text-gray-300"
					label={$i18n.t('Need help? Contact')}
				/>

				<div class=" mt-6 mx-auto relative group w-fit">
					<button
						class="relative z-20 flex px-5 py-2 rounded-full bg-white border border-gray-100 dark:border-none hover:bg-gray-100 text-gray-700 transition font-medium text-sm"
						on:click={async () => {
							location.href = '/';
						}}
					>
						{$i18n.t('Check Again')}
					</button>

					<button
						class="text-xs text-center w-full mt-2 text-gray-400 underline"
						on:click={async () => {
							localStorage.removeItem('token');
							location.href = '/auth';
						}}>{$i18n.t('Sign Out')}</button
					>
				</div>
			</div>
		</div>
	</div>
</div>
