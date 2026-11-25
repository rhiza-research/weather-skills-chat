<script lang="ts">
	import XMarkSolid from '$lib/components/icons/XMarkSolid.svelte';
	import { getContext } from 'svelte';
	import { toast } from 'svelte-sonner';
	import dayjs from 'dayjs';
	import localizedFormat from 'dayjs/plugin/localizedFormat';

	import {
		copyChatShareLink,
		deleteChatShareLink,
		getChatShareLinks,
		shareLinkUrl,
		type ShareLink
	} from '$lib/apis/chats';
	import { copyToClipboard } from '$lib/utils';
	import Modal from '$lib/components/common/Modal.svelte';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import Clipboard from '$lib/components/icons/Clipboard.svelte';
	import GarbageBin from '$lib/components/icons/GarbageBin.svelte';

	const i18n = getContext('i18n');
	dayjs.extend(localizedFormat);

	export let show = false;
	export let chatId: string;

	const DEFAULT_DAYS = 7;
	const MAX_DAYS = 365;

	let days: number = DEFAULT_DAYS;
	let links: ShareLink[] = [];
	// The link being created, shown greyed out above the others until it exists.
	let pending: ShareLink | null = null;
	let showDeleteConfirm = false;
	let deleteId = '';

	$: if (!show) {
		days = DEFAULT_DAYS;
		links = [];
	}
	$: if (show && chatId) loadLinks();
	$: valid = Number.isInteger(days) && days >= 1 && days <= MAX_DAYS;
	$: rows = pending ? [pending, ...links] : links;

	const loadLinks = async () => {
		try {
			links = await getChatShareLinks(localStorage.token, chatId);
		} catch (error) {
			toast.error(`${error}`);
		}
	};

	const createHandler = async () => {
		if (!valid || pending) return;
		pending = {
			id: '',
			created_at: dayjs().unix(),
			expires_at: dayjs().add(days, 'day').unix()
		};
		try {
			await copyChatShareLink(localStorage.token, chatId, days);
			toast.success($i18n.t('Copied shared chat URL to clipboard!'));
			await loadLinks();
		} catch (error) {
			toast.error(`${error}`);
		}
		pending = null;
	};

	const copyLink = async (id: string) => {
		if (await copyToClipboard(shareLinkUrl(id))) {
			toast.success($i18n.t('Copied shared chat URL to clipboard!'));
		}
	};

	const deleteLink = async (id: string) => {
		try {
			await deleteChatShareLink(localStorage.token, chatId, id);
			links = links.filter((link) => link.id !== id);
		} catch (error) {
			toast.error(`${error}`);
		}
	};
</script>

<ConfirmDialog
	bind:show={showDeleteConfirm}
	title={$i18n.t('Delete share link?')}
	message={$i18n.t('Anyone who has this link will no longer be able to open it.')}
	confirmLabel={$i18n.t('Delete')}
	on:confirm={() => deleteLink(deleteId)}
/>

<Modal size="sm" bind:show>
	<div>
		<div class=" flex justify-between dark:text-gray-300 px-5 py-4">
			<h2 class="modal-title">{$i18n.t('Share chat')}</h2>
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
		<hr class="border-line my-2" />

		{#if rows.length}
			<div class="px-5 pt-4 dark:text-gray-200">
				<div class="mb-1 text-xs text-muted">
					{$i18n.t('Active share links')}
				</div>
				<ul class="flex flex-col gap-1.5 max-h-60 overflow-y-auto">
					{#each rows as link (link.id)}
						<li
							class="flex items-center justify-between gap-3 rounded-lg border border-line-strong px-3 py-2 text-xs"
							class:opacity-50={!link.id}
							aria-busy={!link.id}
						>
							<div class="flex flex-col">
								<span>
									{$i18n.t('Created {{DATE}}', {
										DATE: dayjs.unix(link.created_at).format('lll')
									})}
								</span>
								<span class="text-muted">
									{link.expires_at
										? $i18n.t('Expires {{DATE}}', {
												DATE: dayjs.unix(link.expires_at).format('lll')
											})
										: $i18n.t('Never expires')}
								</span>
							</div>
							{#if link.id}
								<div class="flex">
									<button
										type="button"
										class="p-1.5 rounded-xl hover:bg-tint transition"
										aria-label={$i18n.t('Copy link')}
										title={$i18n.t('Copy link')}
										on:click={() => copyLink(link.id)}
									>
										<Clipboard />
									</button>
									<button
										type="button"
										class="p-1.5 rounded-xl hover:bg-tint transition"
										aria-label={$i18n.t('Delete link')}
										title={$i18n.t('Delete link')}
										on:click={() => {
											deleteId = link.id;
											showDeleteConfirm = true;
										}}
									>
										<GarbageBin />
									</button>
								</div>
							{:else}
								<div class="p-1.5"><Spinner className="size-4" /></div>
							{/if}
						</li>
					{/each}
				</ul>
			</div>
		{/if}

		<form
			class="flex flex-col w-full p-5 dark:text-gray-200"
			on:submit|preventDefault={createHandler}
		>
			<label class="flex flex-col w-full">
				<span class="mb-1 text-xs text-muted">{$i18n.t('Expires after (days)')}</span>
				<input
					class="field-outline focus:border-gray-500"
					type="number"
					min="1"
					max={MAX_DAYS}
					step="1"
					required
					bind:value={days}
				/>
			</label>
			<div class="mt-1 text-xs text-muted">
				{valid
					? $i18n.t('Expires {{DATE}}', { DATE: dayjs().add(days, 'day').format('LL') })
					: $i18n.t('Choose between 1 and {{MAX}} days.', { MAX: MAX_DAYS })}
			</div>

			<div class="mt-4 text-sm text-body">
				{$i18n.t(
					'Anyone with this link will be able to see this chat and its files until the expiration date'
				)}
			</div>

			<div class="flex justify-end pt-4">
				<button
					class="px-4 py-1.5 text-sm font-medium bg-inverse hover:bg-gray-900 text-on-inverse dark:hover:bg-gray-100 transition rounded-full disabled:opacity-50"
					type="submit"
					disabled={!!pending || !valid}
				>
					{$i18n.t('Create share link')}
				</button>
			</div>
		</form>
	</div>
</Modal>
