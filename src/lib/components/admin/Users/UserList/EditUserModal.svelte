<script lang="ts">
	import { toast } from 'svelte-sonner';
	import dayjs from 'dayjs';
	import { createEventDispatcher, getContext } from 'svelte';

	import { updateUserById } from '$lib/apis/users';
	import { updateOrganizationById } from '$lib/apis/organizations';

	import Modal from '$lib/components/common/Modal.svelte';
	import localizedFormat from 'dayjs/plugin/localizedFormat';

	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher();
	dayjs.extend(localizedFormat);

	export let show = false;
	export let selectedUser;
	export let selectedOrg = null;
	export let sessionUser;

	let _user = {
		profile_image_url: '',
		name: '',
		email: '',
		password: ''
	};
	let unlimited = false;
	let limitUsd = 300;
	let initialized = false;

	$: if (show && selectedUser && !initialized) {
		_user = { ...selectedUser, password: '' };
		if (selectedOrg) {
			if (selectedOrg.monthly_limit_usd == null) {
				unlimited = true;
				limitUsd = 300;
			} else {
				unlimited = false;
				limitUsd = Number(selectedOrg.monthly_limit_usd);
			}
		}
		initialized = true;
	}
	$: if (!show) {
		initialized = false;
	}

	const submitHandler = async () => {
		const res = await updateUserById(localStorage.token, selectedUser.id, _user).catch((error) => {
			toast.error(`${error}`);
		});

		if (!res) {
			return;
		}

		if (selectedOrg?.id) {
			let monthlyLimit = null;
			if (!unlimited) {
				const parsed = Number(limitUsd);
				if (!Number.isFinite(parsed) || parsed < 0) {
					toast.error($i18n.t('Monthly limit must be a number greater than or equal to 0.'));
					return;
				}
				monthlyLimit = parsed;
			}
			try {
				await updateOrganizationById(localStorage.token, selectedOrg.id, {
					monthly_limit_usd: monthlyLimit
				});
			} catch (error) {
				toast.error(`${error}`);
				return;
			}
		}

		dispatch('save');
		show = false;
	};
</script>

<Modal size="sm" bind:show>
	<div>
		<div class=" flex justify-between dark:text-gray-300 px-5 py-4">
			<div class=" text-lg font-medium self-center">{$i18n.t('Edit User')}</div>
			<button
				class="self-center"
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

		<div class="flex flex-col md:flex-row w-full p-5 md:space-x-4 dark:text-gray-200">
			<div class=" flex flex-col w-full sm:flex-row sm:justify-center sm:space-x-6">
				<form
					class="flex flex-col w-full"
					on:submit|preventDefault={() => {
						submitHandler();
					}}
				>
					<div class=" flex items-center rounded-md py-2 px-4 w-full">
						<div class=" self-center mr-5">
							<img
								src={selectedUser.profile_image_url}
								class=" max-w-[55px] object-cover rounded-full"
								alt="User profile"
							/>
						</div>

						<div>
							<div class=" self-center capitalize font-semibold">{selectedUser.name}</div>

							<div class="text-xs text-gray-500">
								{$i18n.t('Created at')}
								{dayjs(selectedUser.created_at * 1000).format('LL')}
							</div>
						</div>
					</div>

					<hr class="border-gray-100 dark:border-gray-850 my-3 w-full" />

					<div class=" flex flex-col space-y-1.5">
						<div class="flex flex-col w-full">
							<div class=" mb-1 text-xs text-gray-500">{$i18n.t('Email')}</div>

							<div class="flex-1">
								<input
									class="w-full rounded-sm py-2 px-4 text-sm dark:text-gray-300 dark:bg-gray-800 disabled:text-gray-500 dark:disabled:text-gray-500 outline-hidden"
									type="email"
									bind:value={_user.email}
									autocomplete="off"
									required
									disabled={_user.id == sessionUser.id}
								/>
							</div>
						</div>

						<div class="flex flex-col w-full">
							<div class=" mb-1 text-xs text-gray-500">{$i18n.t('Name')}</div>

							<div class="flex-1">
								<input
									class="w-full rounded-sm py-2 px-4 text-sm dark:text-gray-300 dark:bg-gray-800 outline-hidden"
									type="text"
									bind:value={_user.name}
									autocomplete="off"
									required
								/>
							</div>
						</div>

						<div class="flex flex-col w-full">
							<div class=" mb-1 text-xs text-gray-500">{$i18n.t('New Password')}</div>

							<div class="flex-1">
								<input
									class="w-full rounded-sm py-2 px-4 text-sm dark:text-gray-300 dark:bg-gray-800 outline-hidden"
									type="password"
									bind:value={_user.password}
									autocomplete="new-password"
								/>
							</div>
						</div>

						{#if selectedOrg}
							<div class="flex flex-col w-full pt-2">
								<div class=" mb-1 text-xs text-gray-500">{$i18n.t('Monthly usage limit (USD)')}</div>
								<label class="flex items-center gap-2 text-sm mb-2">
									<input type="checkbox" bind:checked={unlimited} />
									{$i18n.t('Unlimited')}
								</label>
								{#if !unlimited}
									<input
										class="w-full rounded-sm py-2 px-4 text-sm dark:text-gray-300 dark:bg-gray-800 outline-hidden"
										type="number"
										min="0"
										step="0.01"
										bind:value={limitUsd}
									/>
								{/if}
							</div>
						{/if}
					</div>

					<div class="flex justify-end pt-3 text-sm font-medium">
						<button
							class=" px-4 py-2 bg-emerald-700 hover:bg-emerald-800 text-gray-100 transition rounded-lg"
							type="submit"
						>
							{$i18n.t('Save')}
						</button>
					</div>
				</form>
			</div>
		</div>
	</div>
</Modal>

<style>
	input::-webkit-outer-spin-button,
	input::-webkit-inner-spin-button {
		/* display: none; <- Crashes Chrome on hover */
		-webkit-appearance: none;
		margin: 0; /* <-- Apparently some margin are still there even though it's hidden */
	}

	.tabs::-webkit-scrollbar {
		display: none; /* for Chrome, Safari and Opera */
	}

	.tabs {
		-ms-overflow-style: none; /* IE and Edge */
		scrollbar-width: none; /* Firefox */
	}

	input[type='number'] {
		-moz-appearance: textfield; /* Firefox */
	}
</style>
