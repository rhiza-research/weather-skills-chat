<script lang="ts">
	import { getAdminDetails } from '$lib/apis/auths';
	import { onMount, getContext } from 'svelte';
	import { config } from '$lib/stores';
	import { helpEmailAddress } from '$lib/constants';

	const i18n = getContext('i18n');

	let adminDetails = null;

	$: helpEmail = helpEmailAddress($config?.help_email);
	$: adminEmail = (adminDetails?.email || '').trim();

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
					{$i18n.t('Account Activation Pending')}
				</div>

				<div class="mt-4 text-center text-sm dark:text-gray-200 w-full">
					{$i18n.t('Thank you for your interest in Weather Skills!')}
				</div>

				<div class="mt-3 text-center text-sm dark:text-gray-200 w-full">
					{$i18n.t(
						'Weather Skills administrators have been notified, and will reach out to you with any follow up questions.'
					)}
				</div>

				<div class="mt-3 text-center text-sm dark:text-gray-200 w-full">
					{#if adminEmail && adminEmail !== helpEmail}
						{$i18n.t('In the meantime feel free to reach out to the administrator at')}
						<a class="underline" href={`mailto:${adminEmail}`}>{adminEmail}</a>
						{$i18n.t('or')}
						<a class="underline" href={`mailto:${helpEmail}`}>{helpEmail}</a>
						{$i18n.t('for more information.')}
					{:else}
						{$i18n.t('In the meantime feel free to reach out to the administrator at')}
						<a class="underline" href={`mailto:${adminEmail || helpEmail}`}
							>{adminEmail || helpEmail}</a
						>
						{$i18n.t('for more information.')}
					{/if}
				</div>

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
