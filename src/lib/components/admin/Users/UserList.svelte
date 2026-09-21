<script>
	import { WEBUI_BASE_URL } from '$lib/constants';
	import { config, user } from '$lib/stores';
	import { onMount, getContext } from 'svelte';

	import dayjs from 'dayjs';
	import relativeTime from 'dayjs/plugin/relativeTime';
	import localizedFormat from 'dayjs/plugin/localizedFormat';
	dayjs.extend(relativeTime);
	dayjs.extend(localizedFormat);

	import { toast } from 'svelte-sonner';

	import { updateUserRole, getUsers, deleteUserById } from '$lib/apis/users';
	import {
		activateOrganization,
		deleteOrganizationById,
		getAllOrganizations,
		updateOrganizationById
	} from '$lib/apis/organizations';
	import { formatTokenCount, formatUsd, remainingUsd, tokenUsageLabel, tokenUsageTooltip } from '$lib/utils/usage';

	import Pagination from '$lib/components/common/Pagination.svelte';
	import ChatBubbles from '$lib/components/icons/ChatBubbles.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import ChevronRight from '$lib/components/icons/ChevronRight.svelte';
	import UserCircleSolid from '$lib/components/icons/UserCircleSolid.svelte';

	import EditUserModal from '$lib/components/admin/Users/UserList/EditUserModal.svelte';
	import EditOrganizationModal from '$lib/components/admin/Users/UserList/EditOrganizationModal.svelte';
	import UserChatsModal from '$lib/components/admin/Users/UserList/UserChatsModal.svelte';
	import AddUserModal from '$lib/components/admin/Users/UserList/AddUserModal.svelte';

	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import Badge from '$lib/components/common/Badge.svelte';
	import Plus from '$lib/components/icons/Plus.svelte';
	import Banner from '$lib/components/common/Banner.svelte';

	const i18n = getContext('i18n');

	export let users = [];

	let orgs = [];
	let search = '';
	let selectedUser = null;
	let page = 1;
	let expandedId = '';
	let activating = '';

	let showDeleteConfirmDialog = false;
	let showAddUserModal = false;
	let showUserChatsModal = false;
	let showEditUserModal = false;
	let showEditOrgModal = false;
	let selectedOrg = null;
	let pendingDelete = null;

	const avatarSrc = (url) =>
		url?.startsWith(WEBUI_BASE_URL) ||
		url?.startsWith('https://www.gravatar.com/avatar/') ||
		url?.startsWith('data:')
			? url
			: '/user.png';

	const kindRank = (org) => {
		if (org.kind === 'workspace' && org.active === false) return 0;
		if (org.kind === 'personal') return 1;
		if (org.kind === 'platform') return 2;
		return 3;
	};

	const loadOrgs = async () => {
		orgs = (await getAllOrganizations(localStorage.token).catch(() => [])) || [];
	};

	const refreshUsers = async () => {
		users = await getUsers(localStorage.token);
		await loadOrgs();
	};

	const updateRoleHandler = async (id, role) => {
		const res = await updateUserRole(localStorage.token, id, role).catch((error) => {
			toast.error(`${error}`);
			return null;
		});
		if (res) {
			await refreshUsers();
		}
	};

	const deleteUserHandler = async (id) => {
		const res = await deleteUserById(localStorage.token, id).catch((error) => {
			toast.error(`${error}`);
			return null;
		});
		if (res) {
			await refreshUsers();
		}
	};

	const deleteOrgHandler = async (id) => {
		try {
			await deleteOrganizationById(localStorage.token, id);
			if (expandedId === id) {
				expandedId = '';
			}
			await loadOrgs();
			toast.success($i18n.t('Organization deleted'));
		} catch (error) {
			toast.error(`${error}`);
		}
	};

	const openDelete = (kind, id, name) => {
		pendingDelete = { kind, id, name };
		showDeleteConfirmDialog = true;
	};

	const confirmPendingDelete = async () => {
		if (!pendingDelete) {
			return;
		}
		if (pendingDelete.kind === 'user') {
			await deleteUserHandler(pendingDelete.id);
		} else {
			await deleteOrgHandler(pendingDelete.id);
		}
		pendingDelete = null;
	};

	const activate = async (id) => {
		activating = id;
		try {
			await activateOrganization(localStorage.token, id);
			await loadOrgs();
			toast.success($i18n.t('Organization activated'));
		} catch (error) {
			toast.error(`${error}`);
		}
		activating = '';
	};

	const toggleCanAdd = async (row, key) => {
		const next = !row[key];
		const kind =
			key === 'can_add_models' ? 'models' : key === 'can_add_skills' ? 'skills' : 'knowledge';
		try {
			await updateOrganizationById(localStorage.token, row.id, {
				[key]: next
			});
			await loadOrgs();
			toast.success(
				next
					? $i18n.t('{{name}} can now add {{kind}}', {
							name: row.displayName,
							kind
						})
					: $i18n.t('{{name}} can no longer add {{kind}}', {
							name: row.displayName,
							kind
						})
			);
		} catch (error) {
			toast.error(`${error}`);
		}
	};

	$: userById = Object.fromEntries((users ?? []).map((item) => [item.id, item]));

	$: rows = (orgs ?? [])
		.filter((org) => org.kind !== 'platform')
		.map((org) => {
			const person = org.kind === 'personal' ? userById[org.id] : null;
			return {
				...org,
				person,
				displayName: person?.name ?? org.name,
				email: person?.email ?? '',
				image: person?.profile_image_url ?? '',
				memberCount: (org.members ?? []).length
			};
		})
		.filter((row) => {
			if (!search.trim()) return true;
			const q = search.toLowerCase();
			const memberHit = (row.members ?? []).some(
				(member) =>
					(member.name || '').toLowerCase().includes(q) ||
					(member.email || '').toLowerCase().includes(q)
			);
			return (
				row.displayName.toLowerCase().includes(q) ||
				row.email.toLowerCase().includes(q) ||
				(row.name || '').toLowerCase().includes(q) ||
				(row.kind || '').toLowerCase().includes(q) ||
				memberHit
			);
		})
		.sort((a, b) => {
			const rank = kindRank(a) - kindRank(b);
			if (rank !== 0) return rank;
			return a.displayName.localeCompare(b.displayName);
		});

	$: paged = rows.slice((page - 1) * 20, page * 20);

	const tokenLine = (usage) => {
		if (!usage) return '—';
		return `${formatTokenCount(usage.prompt_tokens)} / ${formatTokenCount(usage.completion_tokens)} / ${formatTokenCount(usage.total_tokens)} / ${formatTokenCount(usage.uncached_tokens)}`;
	};

	onMount(loadOrgs);
</script>

<ConfirmDialog
	bind:show={showDeleteConfirmDialog}
	title={pendingDelete?.kind === 'organization'
		? $i18n.t('Delete Organization')
		: $i18n.t('Delete User')}
	message={pendingDelete?.kind === 'organization'
		? $i18n.t(
				'This will permanently delete the organization and its shared resources. Type the organization name to confirm.'
			)
		: $i18n.t('This will permanently delete the user. Type the user name to confirm.')}
	inputMatch={pendingDelete?.name ?? ''}
	confirmLabel={$i18n.t('Delete')}
	on:confirm={confirmPendingDelete}
	on:cancel={() => {
		pendingDelete = null;
	}}
/>

{#key selectedUser}
	<EditUserModal
		bind:show={showEditUserModal}
		{selectedUser}
		selectedOrg={selectedUser ? orgs.find((org) => org.id === selectedUser.id) : null}
		sessionUser={$user}
		on:save={refreshUsers}
	/>
{/key}

{#key selectedOrg}
	<EditOrganizationModal bind:show={showEditOrgModal} {selectedOrg} on:save={loadOrgs} />
{/key}

<AddUserModal bind:show={showAddUserModal} on:save={refreshUsers} />
<UserChatsModal bind:show={showUserChatsModal} user={selectedUser} />

{#if ($config?.license_metadata?.seats ?? null) !== null && users.length > $config?.license_metadata?.seats}
	<div class=" mt-1 mb-2 text-xs text-red-500">
		<Banner
			className="mx-0"
			banner={{
				type: 'error',
				title: 'License Error',
				content:
					'Exceeded the number of seats in your license. Please contact support to increase the number of seats.',
				dismissable: true
			}}
		/>
	</div>
{/if}

<div class="mt-0.5 mb-2 gap-1 flex flex-col md:flex-row justify-between">
	<div class="flex md:self-center text-lg font-medium px-0.5">
		<div class="flex-shrink-0">
			{$i18n.t('Users & Organizations')}
		</div>
		<div class="flex self-center w-[1px] h-6 mx-2.5 bg-gray-50 dark:bg-gray-850" />
		<span class="text-lg font-medium text-gray-500 dark:text-gray-300">{rows.length}</span>
	</div>

	<div class="flex gap-1">
		<div class=" flex w-full space-x-2">
			<div class="flex flex-1">
				<div class=" self-center ml-1 mr-3">
					<svg
						xmlns="http://www.w3.org/2000/svg"
						viewBox="0 0 20 20"
						fill="currentColor"
						class="w-4 h-4"
					>
						<path
							fill-rule="evenodd"
							d="M9 3.5a5.5 5.5 0 100 11 5.5 5.5 0 000-11zM2 9a7 7 0 1112.452 4.391l3.328 3.329a.75.75 0 11-1.06 1.06l-3.329-3.328A7 7 0 012 9z"
							clip-rule="evenodd"
						/>
					</svg>
				</div>
				<input
					class=" w-full text-sm pr-4 py-1 rounded-r-xl outline-hidden bg-transparent"
					bind:value={search}
					placeholder={$i18n.t('Search')}
				/>
			</div>

			<div>
				<Tooltip content={$i18n.t('Add User')}>
					<button
						class=" p-2 rounded-xl hover:bg-gray-100 dark:bg-gray-900 dark:hover:bg-gray-850 transition font-medium text-sm flex items-center space-x-1"
						on:click={() => {
							showAddUserModal = !showAddUserModal;
						}}
					>
						<Plus className="size-3.5" />
					</button>
				</Tooltip>
			</div>
		</div>
	</div>
</div>

<div class="overflow-x-auto">
	<div class="min-w-[76rem]">
		<div
			class="org-table-row grid items-end gap-x-3 px-2 pb-1.5 text-[11px] font-semibold text-gray-500 dark:text-gray-400"
		>
			<div class="uppercase text-xs font-bold text-gray-900 dark:text-gray-100">
				{$i18n.t('Name')}
			</div>
			<div class="uppercase text-xs font-bold text-gray-900 dark:text-gray-100">
				{$i18n.t('Type')}
			</div>
			<div class="uppercase text-xs font-bold text-gray-900 dark:text-gray-100">
				{$i18n.t('Members')}
			</div>
			<div class="text-right leading-tight">{$i18n.t('Used')}</div>
			<div class="text-right leading-tight">{$i18n.t('Monthly usage limit')}</div>
			<div class="text-right leading-tight">{$i18n.t('Remaining')}</div>
			<div class="leading-tight">
				<Tooltip content={tokenUsageLabel()} className="inline-flex">
					<span>{$i18n.t('Tokens')}</span>
				</Tooltip>
			</div>
			<div class="text-center leading-tight">{$i18n.t('Allow adding models')}</div>
			<div class="text-center leading-tight">{$i18n.t('Allow adding skills')}</div>
			<div class="text-center leading-tight">{$i18n.t('Allow adding knowledge')}</div>
			<div></div>
		</div>
		<hr class="mt-0.5 border-gray-100 dark:border-gray-850" />

		{#each paged as row, idx (row.id)}
		<div
			class="rounded-lg py-2 {idx % 2 === 0
				? 'bg-gray-50 dark:bg-gray-850/80'
				: 'bg-white dark:bg-gray-900'}"
		>
			<div class="org-table-row grid items-center gap-x-3 px-2">
				{#if row.kind === 'personal'}
					<div class="flex items-center gap-2 min-w-0">
						<span class="shrink-0 w-4"></span>
						{#if row.person}
							<img
								class="rounded-full w-6 h-6 object-cover shrink-0"
								src={avatarSrc(row.image)}
								alt=""
							/>
						{:else}
							<div
								class="rounded-full w-6 h-6 shrink-0 bg-gray-100 dark:bg-gray-850 flex items-center justify-center"
							>
								<UserCircleSolid className="size-4" />
							</div>
						{/if}
						<div class="min-w-0">
							<div class="text-sm font-medium truncate">{row.displayName}</div>
							<div class="text-xs text-gray-500 truncate">
								{#if row.email}
									{row.email}
								{:else if row.description}
									{row.description}
								{/if}
							</div>
						</div>
					</div>
				{:else}
					<button
						class="flex items-center gap-2 min-w-0 text-left"
						on:click={() => {
							expandedId = expandedId === row.id ? '' : row.id;
						}}
					>
						<span
							class="shrink-0 text-gray-400 transition {expandedId === row.id ? 'rotate-90' : ''}"
						>
							<ChevronRight className="size-4" strokeWidth="2" />
						</span>
						<div
							class="rounded-full w-6 h-6 shrink-0 bg-gray-100 dark:bg-gray-850 flex items-center justify-center"
						>
							<UserCircleSolid className="size-4" />
						</div>
						<div class="min-w-0">
							<div class="text-sm font-medium truncate">{row.displayName}</div>
							<div class="text-xs text-gray-500 truncate">
								{#if row.description}
									{row.description}
								{/if}
							</div>
						</div>
					</button>
				{/if}

				<div class="flex items-center gap-1.5 min-w-0">
					{#if row.kind === 'personal'}
						<Badge type="muted" content={$i18n.t('Personal')} />
						{#if row.person?.role === 'pending'}
							<Badge type="warning" content={$i18n.t('Pending')} />
						{/if}
					{:else}
						<Badge type="success" content={$i18n.t('Organization')} />
						{#if row.active === false}
							<Badge type="warning" content={$i18n.t('Pending')} />
						{/if}
					{/if}
				</div>

				<div class="text-sm text-gray-500">
					{row.memberCount}
				</div>

				<div class="text-sm text-right tabular-nums">
					{formatUsd(row.usage?.cost_usd ?? 0, '$0.00')}
				</div>
				<div class="text-sm text-right tabular-nums">
					{formatUsd(row.monthly_limit_usd, $i18n.t('Unlimited'))}
				</div>
				<div class="text-sm text-right tabular-nums text-gray-500">
					{row.monthly_limit_usd == null
						? '—'
						: formatUsd(remainingUsd(row.monthly_limit_usd, row.usage?.cost_usd ?? 0))}
				</div>
				<Tooltip content={tokenUsageTooltip(row.usage)} className="min-w-0 block">
					<div class="text-[11px] text-gray-500 tabular-nums truncate">
						{tokenLine(row.usage)}
					</div>
				</Tooltip>

				<div class="flex justify-center">
					{#if row.kind !== 'platform'}
						<input
							type="checkbox"
							class="cursor-pointer"
							checked={!!row.can_add_models}
							aria-label={$i18n.t('Allow adding models')}
							on:click|stopPropagation
							on:change={() => toggleCanAdd(row, 'can_add_models')}
						/>
					{/if}
				</div>
				<div class="flex justify-center">
					{#if row.kind !== 'platform'}
						<input
							type="checkbox"
							class="cursor-pointer"
							checked={!!row.can_add_skills}
							aria-label={$i18n.t('Allow adding skills')}
							on:click|stopPropagation
							on:change={() => toggleCanAdd(row, 'can_add_skills')}
						/>
					{/if}
				</div>
				<div class="flex justify-center">
					{#if row.kind !== 'platform'}
						<input
							type="checkbox"
							class="cursor-pointer"
							checked={!!row.can_add_knowledge}
							aria-label={$i18n.t('Allow adding knowledge')}
							on:click|stopPropagation
							on:change={() => toggleCanAdd(row, 'can_add_knowledge')}
						/>
					{/if}
				</div>

				<div class="flex justify-end items-center gap-0.5">
					{#if row.kind === 'workspace' && row.active === false}
						<button
							class="text-xs px-2 py-1.5 rounded-lg bg-gray-900 text-white dark:bg-white dark:text-gray-900 disabled:opacity-50"
							disabled={activating === row.id}
							on:click={() => activate(row.id)}
						>
							{$i18n.t('Activate')}
						</button>
					{/if}

					{#if row.person}
						{#if row.person.role === 'pending'}
							<button
								class="text-xs px-2 py-1.5 rounded-lg bg-gray-900 text-white dark:bg-white dark:text-gray-900"
								on:click={() => updateRoleHandler(row.person.id, 'user')}
							>
								{$i18n.t('Activate')}
							</button>
						{/if}

						{#if $config?.features?.enable_admin_chat_access && row.person.id !== $user?.id}
							<Tooltip content={$i18n.t('Chats')}>
								<button
									class="self-center w-fit text-sm px-2 py-2 hover:bg-black/5 dark:hover:bg-white/5 rounded-xl"
									on:click={() => {
										showUserChatsModal = !showUserChatsModal;
										selectedUser = row.person;
									}}
								>
									<ChatBubbles />
								</button>
							</Tooltip>
						{/if}

						<Tooltip content={$i18n.t('Edit User')}>
							<button
								class="self-center w-fit text-sm px-2 py-2 hover:bg-black/5 dark:hover:bg-white/5 rounded-xl"
								on:click={() => {
									showEditUserModal = !showEditUserModal;
									selectedUser = row.person;
								}}
							>
								<svg
									xmlns="http://www.w3.org/2000/svg"
									fill="none"
									viewBox="0 0 24 24"
									stroke-width="1.5"
									stroke="currentColor"
									class="w-4 h-4"
								>
									<path
										stroke-linecap="round"
										stroke-linejoin="round"
										d="m16.862 4.487 1.687-1.688a1.875 1.875 0 1 1 2.652 2.652L6.832 19.82a4.5 4.5 0 0 1-1.897 1.13l-2.685.8.8-2.685a4.5 4.5 0 0 1 1.13-1.897L16.863 4.487Zm0 0L19.5 7.125"
									/>
								</svg>
							</button>
						</Tooltip>

						{#if row.person.id !== $user?.id}
							<Tooltip content={$i18n.t('Delete User')}>
								<button
									class="self-center w-fit text-sm px-2 py-2 hover:bg-black/5 dark:hover:bg-white/5 rounded-xl"
									on:click={() => {
										selectedUser = row.person;
										openDelete('user', row.person.id, row.person.name);
									}}
								>
									<svg
										xmlns="http://www.w3.org/2000/svg"
										fill="none"
										viewBox="0 0 24 24"
										stroke-width="1.5"
										stroke="currentColor"
										class="w-4 h-4"
									>
										<path
											stroke-linecap="round"
											stroke-linejoin="round"
											d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0"
										/>
									</svg>
								</button>
							</Tooltip>
						{/if}
					{:else}
						<Tooltip content={$i18n.t('Edit Organization')}>
							<button
								class="self-center w-fit text-sm px-2 py-2 hover:bg-black/5 dark:hover:bg-white/5 rounded-xl"
								on:click={() => {
									selectedOrg = row;
									showEditOrgModal = !showEditOrgModal;
								}}
							>
								<svg
									xmlns="http://www.w3.org/2000/svg"
									fill="none"
									viewBox="0 0 24 24"
									stroke-width="1.5"
									stroke="currentColor"
									class="w-4 h-4"
								>
									<path
										stroke-linecap="round"
										stroke-linejoin="round"
										d="m16.862 4.487 1.687-1.688a1.875 1.875 0 1 1 2.652 2.652L6.832 19.82a4.5 4.5 0 0 1-1.897 1.13l-2.685.8.8-2.685a4.5 4.5 0 0 1 1.13-1.897L16.863 4.487Zm0 0L19.5 7.125"
									/>
								</svg>
							</button>
						</Tooltip>

						{#if row.kind === 'workspace'}
							<Tooltip content={$i18n.t('Delete Organization')}>
								<button
									class="self-center w-fit text-sm px-2 py-2 hover:bg-black/5 dark:hover:bg-white/5 rounded-xl"
									on:click={() => openDelete('organization', row.id, row.name)}
								>
									<svg
										xmlns="http://www.w3.org/2000/svg"
										fill="none"
										viewBox="0 0 24 24"
										stroke-width="1.5"
										stroke="currentColor"
										class="w-4 h-4"
									>
										<path
											stroke-linecap="round"
											stroke-linejoin="round"
											d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0"
										/>
									</svg>
								</button>
							</Tooltip>
						{/if}
					{/if}
				</div>
			</div>

			{#if row.kind !== 'personal' && expandedId === row.id}
				<div class="ml-10 mt-1 mb-2 rounded-lg bg-gray-50 dark:bg-gray-850/60 px-3 py-2">
					{#if (row.members ?? []).length === 0}
						<div class="text-xs text-gray-500 py-1">{$i18n.t('No members yet.')}</div>
					{:else}
						{#each row.members as member (member.user_id)}
							<div class="flex items-center justify-between gap-3 py-1.5 text-sm">
								<div class="flex items-center gap-2 min-w-0">
									<img
										class="rounded-full w-5 h-5 object-cover shrink-0"
										src={avatarSrc(member.profile_image_url)}
										alt=""
									/>
									<div class="min-w-0">
										<div class="truncate">{member.name ?? member.user_id}</div>
										<div class="text-xs text-gray-500 truncate">{member.email ?? ''}</div>
									</div>
								</div>
								<div class="text-xs text-gray-500 capitalize shrink-0">{member.role}</div>
							</div>
						{/each}
					{/if}
				</div>
			{/if}
		</div>
	{:else}
		<div class="text-sm text-gray-500 py-6 text-center">
			{$i18n.t('No users or organizations yet.')}
		</div>
	{/each}
	</div>
</div>

<div class=" text-gray-500 text-xs mt-1.5 text-right">
	ⓘ {$i18n.t('Admin access is granted by membership in the Platform organization.')}
</div>

<Pagination bind:page count={rows.length} />

<style>
	.org-table-row {
		grid-template-columns:
			minmax(0, 1.5fr)
			7.25rem
			4.25rem
			5.25rem
			7.25rem
			6.25rem
			minmax(0, 0.9fr)
			4.75rem
			4.75rem
			5.25rem
			8.5rem;
	}

	.org-table-row > :global(*) {
		min-width: 0;
	}
</style>
