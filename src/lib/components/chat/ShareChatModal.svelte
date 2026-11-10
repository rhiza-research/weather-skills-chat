<script lang="ts">
	import { getContext } from 'svelte';
	import { toast } from 'svelte-sonner';
	import dayjs from 'dayjs';
	import localizedFormat from 'dayjs/plugin/localizedFormat';

	import { copyChatShareLink } from '$lib/apis/chats';
	import Modal from '$lib/components/common/Modal.svelte';

	const i18n = getContext('i18n');
	dayjs.extend(localizedFormat);

	export let show = false;
	export let chatId: string;

	const DEFAULT_DAYS = 7;
	const MAX_DAYS = 365;

	let days: number = DEFAULT_DAYS;
	let loading = false;

	$: if (!show) days = DEFAULT_DAYS;
	$: valid = Number.isInteger(days) && days >= 1 && days <= MAX_DAYS;

	const createHandler = async () => {
		if (!valid) return;
		loading = true;
		try {
			await copyChatShareLink(localStorage.token, chatId, days);
			toast.success($i18n.t('Copied shared chat URL to clipboard!'));
			show = false;
		} catch (error) {
			toast.error(`${error}`);
		}
		loading = false;
	};
</script>

<Modal size="sm" bind:show>
	<div>
		<div class=" flex justify-between dark:text-gray-300 px-5 py-4">
			<div class=" text-lg font-medium self-center">{$i18n.t('Share chat')}</div>
			<button
				class="self-center"
				aria-label={$i18n.t('Close')}
				on:click={() => {
					show = false;
				}}
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					viewBox="0 0 20 20"
					fill="currentColor"
					class="w-5 h-5"
				>
					<path
						d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z"
					/>
				</svg>
			</button>
		</div>
		<hr class="border-gray-100 dark:border-gray-850" />

		<form
			class="flex flex-col w-full p-5 dark:text-gray-200"
			on:submit|preventDefault={createHandler}
		>
			<label class="flex flex-col w-full">
				<span class="mb-1 text-xs text-gray-500">{$i18n.t('Expires after (days)')}</span>
				<input
					class="w-full text-sm bg-transparent rounded-lg border border-gray-300 dark:border-gray-700 px-3 py-2 outline-hidden focus:border-gray-500"
					type="number"
					min="1"
					max={MAX_DAYS}
					step="1"
					required
					bind:value={days}
				/>
			</label>
			<div class="mt-1 text-xs text-gray-500">
				{valid
					? $i18n.t('Expires {{DATE}}', { DATE: dayjs().add(days, 'day').format('LL') })
					: $i18n.t('Choose between 1 and {{MAX}} days.', { MAX: MAX_DAYS })}
			</div>

			<div class="mt-4 text-sm text-gray-600 dark:text-gray-300">
				{$i18n.t(
					'Anyone with this link will be able to see this chat and its files until the expiration date'
				)}
			</div>

			<div class="flex justify-end pt-4">
				<button
					class="px-3.5 py-1.5 text-sm font-medium bg-black hover:bg-gray-900 text-white dark:bg-white dark:text-black dark:hover:bg-gray-100 transition rounded-full disabled:opacity-50"
					type="submit"
					disabled={loading || !valid}
				>
					{$i18n.t('Create share link')}
				</button>
			</div>
		</form>
	</div>
</Modal>
