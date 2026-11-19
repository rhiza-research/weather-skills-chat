<script lang="ts">
	import XMarkSolid from '$lib/components/icons/XMarkSolid.svelte';
	import { getContext } from 'svelte';
	import { toast } from 'svelte-sonner';

	import { requestCreditIncrease } from '$lib/apis/usage';
	import Modal from '$lib/components/common/Modal.svelte';
	import Textarea from '$lib/components/common/Textarea.svelte';

	const i18n = getContext('i18n');

	export let show = false;

	let credits: number | null = null;
	let reason = '';
	let loading = false;

	$: if (!show) {
		credits = null;
		reason = '';
	}

	const submitHandler = async () => {
		if (!reason.trim()) {
			toast.error($i18n.t('Please say why you need more credits.'));
			return;
		}
		const amount = credits == null || `${credits}` === '' ? null : Number(credits);
		if (amount != null && (!Number.isFinite(amount) || amount <= 0)) {
			toast.error($i18n.t('Credits must be a number greater than 0.'));
			return;
		}
		loading = true;
		try {
			await requestCreditIncrease(localStorage.token, {
				credits: amount,
				reason: reason.trim()
			});
			toast.success($i18n.t('Request sent. An admin will get back to you by email.'));
			show = false;
		} catch (error: any) {
			toast.error(error?.detail ?? `${error}`);
		}
		loading = false;
	};
</script>

<Modal size="sm" bind:show>
	<div>
		<div class=" flex justify-between dark:text-gray-300 px-5 py-4">
			<h2 class="modal-title">{$i18n.t('Request credit increase')}</h2>
			<button
				class="self-center"
				aria-label={$i18n.t('Close')}
				on:click={() => {
					show = false;
				}}
			>
				<XMarkSolid className="size-5" />
			</button>
		</div>
		<hr class="divider" />

		<div class="flex flex-col w-full p-5 dark:text-gray-200">
			<form class="flex flex-col w-full" on:submit|preventDefault={submitHandler}>
				<div class="text-sm text-muted mb-3">
					{$i18n.t('Your request is emailed to the admins who can raise this limit.')}
				</div>

				<div class="flex flex-col w-full">
					<div class="mb-0.5 text-xs text-muted">
						{$i18n.t('Additional credits (optional)')}
					</div>
					<input
						class="field-bare text-sm"
						type="number"
						min="0"
						step="1"
						bind:value={credits}
						placeholder="100"
					/>
				</div>

				<div class="flex flex-col w-full mt-3">
					<div class="mb-0.5 text-xs text-muted">{$i18n.t('What do you need them for?')}</div>
					<Textarea
						className="w-full text-sm bg-transparent outline-hidden resize-none"
						rows={3}
						bind:value={reason}
						placeholder={$i18n.t('e.g. Running seasonal outlooks for the next planting season')}
					/>
				</div>

				<div class="flex justify-end pt-4">
					<button
						class="px-4 py-1.5 text-sm font-medium bg-black hover:bg-gray-900 text-white dark:bg-white dark:text-black dark:hover:bg-gray-100 transition rounded-full disabled:opacity-50"
						type="submit"
						disabled={loading}
					>
						{$i18n.t('Send request')}
					</button>
				</div>
			</form>
		</div>
	</div>
</Modal>
