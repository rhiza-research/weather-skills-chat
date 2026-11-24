<script lang="ts">
	import Trash from '$lib/components/icons/Trash.svelte';
	import MagnifyingGlassSolid from '$lib/components/icons/MagnifyingGlassSolid.svelte';
	import fileSaver from 'file-saver';
	const { saveAs } = fileSaver;
	import { toast } from 'svelte-sonner';
	import dayjs from 'dayjs';
	import { getContext, createEventDispatcher } from 'svelte';
	import localizedFormat from 'dayjs/plugin/localizedFormat';

	dayjs.extend(localizedFormat);

	const dispatch = createEventDispatcher();

	import {
		archiveChatById,
		deleteChatById,
		getAllArchivedChats,
		getArchivedChatList
	} from '$lib/apis/chats';

	import Modal from '$lib/components/common/Modal.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import UnarchiveAllConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	const i18n = getContext('i18n');

	export let show = false;

	let chats = [];

	let searchValue = '';
	let showUnarchiveAllConfirmDialog = false;

	const unarchiveChatHandler = async (chatId) => {
		const res = await archiveChatById(localStorage.token, chatId).catch((error) => {
			toast.error(`${error}`);
		});

		chats = await getArchivedChatList(localStorage.token);
		dispatch('change');
	};

	const deleteChatHandler = async (chatId) => {
		const res = await deleteChatById(localStorage.token, chatId).catch((error) => {
			toast.error(`${error}`);
		});

		chats = await getArchivedChatList(localStorage.token);
	};

	const exportChatsHandler = async () => {
		const chats = await getAllArchivedChats(localStorage.token);
		let blob = new Blob([JSON.stringify(chats)], {
			type: 'application/json'
		});
		saveAs(blob, `${$i18n.t('archived-chat-export')}-${Date.now()}.json`);
	};

	const unarchiveAllHandler = async () => {
		for (const chat of chats) {
			await archiveChatById(localStorage.token, chat.id);
		}
		chats = await getArchivedChatList(localStorage.token);
	};

	$: if (show) {
		(async () => {
			chats = await getArchivedChatList(localStorage.token);
		})();
	}
</script>

<UnarchiveAllConfirmDialog
	bind:show={showUnarchiveAllConfirmDialog}
	message={$i18n.t('Are you sure you want to unarchive all archived chats?')}
	confirmLabel={$i18n.t('Unarchive All')}
	on:confirm={() => {
		unarchiveAllHandler();
	}}
/>

<Modal size="lg" bind:show>
	<div>
		<div class=" flex justify-between dark:text-gray-300 px-5 pt-4 pb-1">
			<h2 class="modal-title">{$i18n.t('Archived Chats')}</h2>
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
					class="size-5"
				>
					<path
						fill-rule="evenodd"
						d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z"
						clip-rule="evenodd"
					/>
				</svg>
			</button>
		</div>

		<div class="flex flex-col w-full px-5 pb-4 dark:text-gray-200">
			<div class=" flex w-full mt-2 space-x-2">
				<div class="flex flex-1">
					<div class=" self-center ml-1 mr-3">
						<MagnifyingGlassSolid className="size-4" />
					</div>
					<input
						class=" w-full text-sm pr-4 py-1 rounded-r-xl outline-hidden bg-transparent"
						bind:value={searchValue}
						placeholder={$i18n.t('Search Chats')}
					/>
				</div>
			</div>
			<hr class="border-line my-2" />
			<div class=" flex flex-col w-full sm:flex-row sm:justify-center sm:space-x-6">
				{#if chats.length > 0}
					<div class="w-full">
						<div class="text-left text-sm w-full mb-3 max-h-[22rem] overflow-y-scroll">
							<div class="relative overflow-x-auto">
								<table class="w-full text-sm text-left text-body table-auto">
									<thead
										class="text-xs text-body uppercase bg-transparent border-b-2 border-line"
									>
										<tr>
											<th scope="col" class="px-3 py-2"> {$i18n.t('Name')} </th>
											<th scope="col" class="px-3 py-2 hidden md:flex">
												{$i18n.t('Created At')}
											</th>
											<th scope="col" class="px-3 py-2 text-right" />
										</tr>
									</thead>
									<tbody>
										{#each chats.filter((c) => searchValue === '' || c.title
													.toLowerCase()
													.includes(searchValue.toLowerCase())) as chat, idx}
											<tr
												class="bg-transparent {idx !== chats.length - 1 &&
													'border-b'} dark:bg-gray-900 border-line text-xs"
											>
												<td class="px-3 py-1 w-2/3">
													<a href="/c/{chat.id}" target="_blank">
														<div class=" underline line-clamp-1">
															{chat.title}
														</div>
													</a>
												</td>

												<td class=" px-3 py-1 hidden md:flex h-[2.5rem]">
													<div class="my-auto">
														{dayjs(chat.created_at * 1000).format('LLL')}
													</div>
												</td>

												<td class="px-3 py-1 text-right">
													<div class="flex justify-end w-full">
														<Tooltip content={$i18n.t('Unarchive Chat')}>
															<button
																class="btn-ghost"
																on:click={async () => {
																	unarchiveChatHandler(chat.id);
																}}
															>
																<svg
																	xmlns="http://www.w3.org/2000/svg"
																	fill="none"
																	viewBox="0 0 24 24"
																	stroke-width="1.5"
																	stroke="currentColor"
																	class="size-4"
																>
																	<path
																		stroke-linecap="round"
																		stroke-linejoin="round"
																		d="M9 8.25H7.5a2.25 2.25 0 0 0-2.25 2.25v9a2.25 2.25 0 0 0 2.25 2.25h9a2.25 2.25 0 0 0 2.25-2.25v-9a2.25 2.25 0 0 0-2.25-2.25H15m0-3-3-3m0 0-3 3m3-3V15"
																	/>
																</svg>
															</button>
														</Tooltip>

														<Tooltip content={$i18n.t('Delete Chat')}>
															<button
																class="btn-ghost"
																on:click={async () => {
																	deleteChatHandler(chat.id);
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
						</div>

						<div class="flex flex-wrap text-sm font-medium gap-1.5 mt-2 m-1 justify-end w-full">
							<button
								class=" px-4 py-1.5 font-medium hover:bg-tint outline outline-1 outline-gray-300 dark:outline-gray-800 rounded-3xl"
								on:click={() => {
									showUnarchiveAllConfirmDialog = true;
								}}
							>
								{$i18n.t('Unarchive All Archived Chats')}
							</button>

							<button
								class="px-4 py-1.5 font-medium hover:bg-tint outline outline-1 outline-gray-300 dark:outline-gray-800 rounded-3xl"
								on:click={() => {
									exportChatsHandler();
								}}
							>
								{$i18n.t('Export All Archived Chats')}
							</button>
						</div>
					</div>
				{:else}
					<div class="text-left text-sm w-full mb-8">
						{$i18n.t('You have no archived conversations.')}
					</div>
				{/if}
			</div>
		</div>
	</div>
</Modal>
