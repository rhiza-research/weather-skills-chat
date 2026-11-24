<script lang="ts">
	import { getContext } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { updateUserPassword } from '$lib/apis/auths';

	const i18n = getContext('i18n');

	let show = false;
	let currentPassword = '';
	let newPassword = '';
	let newPasswordConfirm = '';

	const updatePasswordHandler = async () => {
		if (newPassword === newPasswordConfirm) {
			const res = await updateUserPassword(localStorage.token, currentPassword, newPassword).catch(
				(error) => {
					toast.error(`${error}`);
					return null;
				}
			);

			if (res) {
				toast.success($i18n.t('Successfully updated.'));
			}

			currentPassword = '';
			newPassword = '';
			newPasswordConfirm = '';
		} else {
			toast.error(
				`The passwords you entered don't quite match. Please double-check and try again.`
			);
			newPassword = '';
			newPasswordConfirm = '';
		}
	};
</script>

<form
	class="flex flex-col text-sm"
	on:submit|preventDefault={() => {
		updatePasswordHandler();
	}}
>
	<div class="flex justify-between items-center text-sm">
		<div class="my-1.5 text-sm font-medium">{$i18n.t('Change Password')}</div>
		<button
			class="btn-secondary"
			type="button"
			on:click={() => {
				show = !show;
			}}>{show ? $i18n.t('Hide') : $i18n.t('Show')}</button
		>
	</div>

	{#if show}
		<div class=" py-2.5 space-y-1.5">
			<div class="flex flex-col w-full">
				<div class="mb-1 text-xs text-muted">{$i18n.t('Current Password')}</div>

				<div class="flex-1">
					<input
						class="field-bare dark:text-gray-300"
						type="password"
						bind:value={currentPassword}
						placeholder={$i18n.t('Enter your current password')}
						autocomplete="current-password"
						required
					/>
				</div>
			</div>

			<div class="flex flex-col w-full">
				<div class="mb-1 text-xs text-muted">{$i18n.t('New Password')}</div>

				<div class="flex-1">
					<input
						class="field-bare text-sm dark:text-gray-300"
						type="password"
						bind:value={newPassword}
						placeholder={$i18n.t('Enter your new password')}
						autocomplete="new-password"
						required
					/>
				</div>
			</div>

			<div class="flex flex-col w-full">
				<div class="mb-1 text-xs text-muted">{$i18n.t('Confirm Password')}</div>

				<div class="flex-1">
					<input
						class="field-bare text-sm dark:text-gray-300"
						type="password"
						bind:value={newPasswordConfirm}
						placeholder={$i18n.t('Confirm your new password')}
						autocomplete="off"
						required
					/>
				</div>
			</div>
		</div>

		<div class="mt-3 flex justify-end">
			<button class="btn-primary">
				{$i18n.t('Update password')}
			</button>
		</div>
	{/if}
</form>
