<script lang="ts">
	import Trash from '$lib/components/icons/Trash.svelte';
	import XMarkSolid from '$lib/components/icons/XMarkSolid.svelte';
	import { toast } from 'svelte-sonner';
	import dayjs from 'dayjs';
	import { getContext, createEventDispatcher } from 'svelte';
	import localizedFormat from 'dayjs/plugin/localizedFormat';

	const dispatch = createEventDispatcher();
	dayjs.extend(localizedFormat);

	import { getChatListByUserId, deleteChatById, getArchivedChatList } from '$lib/apis/chats';

	import Modal from '$lib/components/common/Modal.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';

	const i18n = getContext('i18n');

	export let show = false;
	export let user;

	let chats = null;
	let showDeleteConfirmDialog = false;
	let chatToDelete = null;

	const deleteChatHandler = async (chatId) => {
		const res = await deleteChatById(localStorage.token, chatId).catch((error) => {
			toast.error(`${error}`);
		});

		chats = await getChatListByUserId(localStorage.token, user.id);
	};

	$: if (show) {
		(async () => {
			if (user.id) {
				chats = await getChatListByUserId(localStorage.token, user.id);
			}
		})();
	} else {
		chats = null;
	}

	let sortKey = 'updated_at'; // default sort key
	let sortOrder = 'desc'; // default sort order
	function setSortKey(key) {
		if (sortKey === key) {
			sortOrder = sortOrder === 'asc' ? 'desc' : 'asc';
		} else {
			sortKey = key;
			sortOrder = 'asc';
		}
	}
</script>

<ConfirmDialog
	bind:show={showDeleteConfirmDialog}
	on:confirm={() => {
		if (chatToDelete) {
			deleteChatHandler(chatToDelete);
			chatToDelete = null;
		}
	}}
/>

<Modal size="lg" bind:show>
	<div class=" flex justify-between dark:text-gray-300 px-5 pt-4">
		<div class=" modal-title capitalize">
			{$i18n.t("{{user}}'s Chats", { user: user.name })}
		</div>
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

	<div class="flex flex-col md:flex-row w-full px-5 pt-2 pb-4 md:space-x-4 dark:text-gray-200">
		<div class=" flex flex-col w-full sm:flex-row sm:justify-center sm:space-x-6">
			{#if chats}
				{#if chats.length > 0}
					<div class="text-left text-sm w-full mb-4 max-h-[22rem] overflow-y-scroll">
						<div class="relative overflow-x-auto">
							<table class="w-full text-sm text-left text-body table-auto">
								<thead
									class="text-xs text-body uppercase bg-transparent border-b-2 dark:border-gray-850"
								>
									<tr>
										<th
											scope="col"
											class="px-3 py-2 cursor-pointer select-none"
											on:click={() => setSortKey('title')}
										>
											{$i18n.t('Title')}
											{#if sortKey === 'title'}
												{sortOrder === 'asc' ? '▲' : '▼'}
											{:else}
												<span class="invisible">▲</span>
											{/if}
										</th>
										<th
											scope="col"
											class="px-3 py-2 hidden md:flex cursor-pointer select-none justify-end"
											on:click={() => setSortKey('updated_at')}
										>
											{$i18n.t('Updated at')}
											{#if sortKey === 'updated_at'}
												{sortOrder === 'asc' ? '▲' : '▼'}
											{:else}
												<span class="invisible">▲</span>
											{/if}
										</th>
										<th scope="col" class="px-3 py-2 text-right" />
									</tr>
								</thead>
								<tbody>
									{#each chats.sort((a, b) => {
										if (a[sortKey] < b[sortKey]) return sortOrder === 'asc' ? -1 : 1;
										if (a[sortKey] > b[sortKey]) return sortOrder === 'asc' ? 1 : -1;
										return 0;
									}) as chat, idx}
										<tr
											class="bg-transparent {idx !== chats.length - 1 &&
												'border-b'} dark:bg-gray-900 dark:border-gray-850 text-xs"
										>
											<td class="px-3 py-1">
												<a href="/s/{chat.id}" target="_blank">
													<div class=" underline line-clamp-1 max-w-96">
														{chat.title}
													</div>
												</a>
											</td>

											<td class=" px-3 py-1 hidden md:flex h-[2.5rem] justify-end">
												<div class="my-auto shrink-0">
													{dayjs(chat.updated_at * 1000).format('LLL')}
												</div>
											</td>

											<td class="px-3 py-1 text-right">
												<div class="flex justify-end w-full">
													<Tooltip content={$i18n.t('Delete Chat')}>
														<button
															class="btn-ghost"
															on:click={async () => {
																chatToDelete = chat.id;
																showDeleteConfirmDialog = true;
															}}
														>
															<Trash className="size-4" />
														</button>
													</Tooltip>
												</div>
											</td>
										</tr>
									{/each}
								</tbody>
							</table>
						</div>
						<!-- {#each chats as chat}
							<div>
								{JSON.stringify(chat)}
							</div>
						{/each} -->
					</div>
				{:else}
					<div class="text-left text-sm w-full mb-8">
						{user.name}
						{$i18n.t('has no conversations.')}
					</div>
				{/if}
			{:else}
				<Spinner />
			{/if}
		</div>
	</div>
</Modal>
