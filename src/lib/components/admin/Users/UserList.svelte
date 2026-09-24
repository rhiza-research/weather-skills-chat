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
		addOrganizationMember,
		deleteOrganizationById,
		removeOrganizationMember,
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
	import {
		createPlatformInvitation,
		getPlatformInvitations,
		resendPlatformInvitation,
		cancelPlatformInvitation
	} from '$lib/apis/invitations';

	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import Modal from '$lib/components/common/Modal.svelte';
	import Badge from '$lib/components/common/Badge.svelte';
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
	let showRemoveMemberConfirm = false;
	let pendingRemoveMember = null;
	let showInvite = false;
	let inviteEmail = '';
	let inviteLimit = 300;
	let inviteUnlimited = false;
	let inviteRole = 'user';
	let inviting = false;
	let memberUserId = '';
	let memberRole = 'user';
	let addingMember = false;
	let showAddMember = false;
	let invitations = [];
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
		if (org.kind === 'invite') return -1;
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

	$: rows = [
		...(orgs ?? [])
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
			}),
		...(invitations ?? []).map((invite) => ({
			id: `invite:${invite.id}`,
			kind: 'invite',
			displayName: invite.email,
			email: invite.email,
			name: invite.email,
			invite
		}))
	]
		.filter((row) => {
			if (!search.trim()) return true;
			const q = search.toLowerCase();
			const memberHit = (row.members ?? []).some(
				(member) =>
					(member.name || '').toLowerCase().includes(q) ||
					(member.email || '').toLowerCase().includes(q)
			);
			return (
				(row.displayName || '').toLowerCase().includes(q) ||
				(row.email || '').toLowerCase().includes(q) ||
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

	const loadInvitations = async () => {
		try {
			invitations = await getPlatformInvitations(localStorage.token);
		} catch (error) {
			toast.error(`${error}`);
		}
	};

	const inviteLimitValue = () => {
		if (inviteUnlimited) return null;
		const parsed = Number(inviteLimit);
		if (!Number.isFinite(parsed) || parsed < 0) {
			toast.error(
				$i18n.t('Monthly usage limit must be a number greater than or equal to 0.')
			);
			return undefined;
		}
		return parsed;
	};

	const sendInvite = async () => {
		if (!inviteEmail.trim()) return;
		const monthlyLimit = inviteLimitValue();
		if (monthlyLimit === undefined) return;
		inviting = true;
		try {
			await createPlatformInvitation(
				localStorage.token,
				inviteEmail.trim(),
				monthlyLimit,
				inviteRole
			);
			inviteEmail = '';
			inviteRole = 'user';
			showInvite = false;
			toast.success($i18n.t('Invitation sent'));
			await loadInvitations();
		} catch (error) {
			toast.error(`${error}`);
		}
		inviting = false;
	};

	const resendInvite = async (id) => {
		try {
			await resendPlatformInvitation(localStorage.token, id);
			toast.success($i18n.t('Invitation resent'));
			await loadInvitations();
		} catch (error) {
			toast.error(`${error}`);
		}
	};

	const candidatesFor = (row) => {
		const memberIds = new Set((row.members ?? []).map((member) => member.user_id));
		return (users ?? []).filter((person) => person?.id && !memberIds.has(person.id));
	};

	const addExistingMember = async (row) => {
		if (!memberUserId) return;
		const role = row.kind === 'platform' ? 'admin' : memberRole;
		addingMember = true;
		try {
			await addOrganizationMember(localStorage.token, row.id, memberUserId, role);
			memberUserId = '';
			memberRole = row.kind === 'platform' ? 'admin' : 'user';
			showAddMember = false;
			toast.success($i18n.t('Member added'));
			await loadOrgs();
		} catch (error) {
			toast.error(`${error}`);
		}
		addingMember = false;
	};

	const askRemoveMember = (row, member) => {
		pendingRemoveMember = {
			orgId: row.id,
			orgName: row.displayName || row.name,
			userId: member.user_id,
			name: member.name || member.email || member.user_id
		};
		showRemoveMemberConfirm = true;
	};

	const confirmRemoveMember = async () => {
		if (!pendingRemoveMember) return;
		try {
			await removeOrganizationMember(
				localStorage.token,
				pendingRemoveMember.orgId,
				pendingRemoveMember.userId
			);
			toast.success($i18n.t('Member removed'));
			await loadOrgs();
		} catch (error) {
			toast.error(`${error}`);
		}
		pendingRemoveMember = null;
	};

	const cancelInvite = async (id) => {
		try {
			await cancelPlatformInvitation(localStorage.token, id);
			toast.success($i18n.t('Invitation canceled'));
			await loadInvitations();
		} catch (error) {
			toast.error(`${error}`);
		}
	};

	onMount(async () => {
		await loadOrgs();
		await loadInvitations();
	});
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

<ConfirmDialog
	bind:show={showRemoveMemberConfirm}
	title={$i18n.t('Remove member')}
	message={$i18n.t('Remove {{name}} from {{organization}}?', {
		name: pendingRemoveMember?.name ?? '',
		organization: pendingRemoveMember?.orgName ?? ''
	})}
	confirmLabel={$i18n.t('Remove')}
	onConfirm={confirmRemoveMember}
	on:cancel={() => {
		pendingRemoveMember = null;
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
				<button
					class="px-3 py-1.5 rounded-lg bg-gray-900 text-white dark:bg-white dark:text-gray-900 transition font-medium text-sm flex items-center gap-1.5"
					type="button"
					on:click={() => {
						inviteEmail = '';
						inviteLimit = 300;
						inviteUnlimited = false;
						inviteRole = 'user';
						showInvite = true;
					}}
				>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						viewBox="0 0 20 20"
						fill="currentColor"
						class="size-4"
					>
						<path
							d="M10.75 4.75a.75.75 0 0 0-1.5 0v4.5h-4.5a.75.75 0 0 0 0 1.5h4.5v4.5a.75.75 0 0 0 1.5 0v-4.5h4.5a.75.75 0 0 0 0-1.5h-4.5v-4.5Z"
						/>
					</svg>
					{$i18n.t('Invite a user')}
				</button>
			</div>
		</div>
	</div>
</div>

<Modal bind:show={showInvite} size="sm">
	<div>
		<div class="flex justify-between dark:text-gray-300 px-5 pt-4 pb-2">
			<div class="text-lg font-medium self-center">{$i18n.t('Invite a user')}</div>
			<button
				class="self-center"
				type="button"
				on:click={() => {
					showInvite = false;
				}}
			>
				<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-5 h-5">
					<path
						d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z"
					/>
				</svg>
			</button>
		</div>
		<hr class="border-gray-100 dark:border-gray-850" />
		<form class="flex flex-col gap-3 p-5" on:submit|preventDefault={sendInvite}>
			<input
				class="w-full text-sm py-2 px-3 rounded-lg bg-gray-50 dark:bg-gray-850 outline-hidden"
				type="email"
				required
				placeholder={$i18n.t('Email')}
				bind:value={inviteEmail}
			/>
			<div>
				<div class="mb-1 text-xs text-gray-500">{$i18n.t('Monthly usage limit')}</div>
				<label class="flex items-center gap-2 text-sm">
					<input type="checkbox" bind:checked={inviteUnlimited} />
					{$i18n.t('Unlimited')}
				</label>
				{#if !inviteUnlimited}
					<div class="flex items-center gap-1.5 mt-2">
						<span class="text-sm text-gray-500">$</span>
						<input
							class="w-full text-sm py-2 px-3 rounded-lg bg-gray-50 dark:bg-gray-850 outline-hidden"
							type="number"
							min="0"
							step="0.01"
							bind:value={inviteLimit}
						/>
					</div>
				{/if}
			</div>
			<label class="block">
				<div class="mb-1 text-xs text-gray-500">{$i18n.t('Role')}</div>
				<select
					class="w-full text-sm py-2 px-3 rounded-lg bg-gray-50 dark:bg-gray-850 outline-hidden"
					bind:value={inviteRole}
				>
					<option value="user">{$i18n.t('User')}</option>
					<option value="admin">{$i18n.t('Admin')}</option>
				</select>
			</label>
			<div class="flex justify-end">
				<button
					class="px-3.5 py-1.5 text-sm font-medium bg-black hover:bg-gray-900 text-white dark:bg-white dark:text-black dark:hover:bg-gray-100 transition rounded-full disabled:opacity-50"
					type="submit"
					disabled={inviting}
				>
					{$i18n.t('Send invite')}
				</button>
			</div>
		</form>
	</div>
</Modal>

<div class="overflow-x-auto">
	<div class="org-table">
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
				{#if row.kind === 'invite'}
					<div class="flex items-center gap-2 min-w-0">
						<span class="shrink-0 w-4"></span>
						<div
							class="rounded-full w-6 h-6 shrink-0 bg-gray-100 dark:bg-gray-850 flex items-center justify-center"
						>
							<UserCircleSolid className="size-4" />
						</div>
						<div class="min-w-0">
							<div class="text-sm font-medium truncate">{row.email}</div>
							<div class="text-xs text-gray-500 truncate">
								{$i18n.t('Sent')} {dayjs(row.invite.created_at * 1000).format('LL')}
								· {row.invite.role === 'admin' ? $i18n.t('Admin') : $i18n.t('User')}
								· {row.invite.expired
									? $i18n.t('Expired')
									: `${$i18n.t('Expires')} ${dayjs(row.invite.expires_at * 1000).format('LL')}`}
							</div>
						</div>
					</div>
				{:else if row.kind === 'personal'}
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
							const opening = expandedId !== row.id;
							expandedId = opening ? row.id : '';
							showAddMember = false;
							if (opening) {
								memberUserId = '';
								memberRole = row.kind === 'platform' ? 'admin' : 'user';
							}
						}}
					>
						<span
							class="shrink-0 text-gray-400 transition {expandedId === row.id ? 'rotate-90' : ''}"
						>
							<ChevronRight className="size-4" strokeWidth="2" />
						</span>
						{#if row.logo}
							<img
								class="rounded-full w-6 h-6 object-cover shrink-0"
								src={row.logo}
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
								{#if row.description}
									{row.description}
								{/if}
							</div>
						</div>
					</button>
				{/if}

				<div class="type-tags flex flex-wrap items-center gap-1">
					{#if row.kind === 'invite'}
						<Badge type="muted" content={$i18n.t('Invite')} />
						<Badge
							type="warning"
							content={row.invite.expired ? $i18n.t('Expired') : $i18n.t('Pending')}
						/>
					{:else if row.kind === 'personal'}
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

				<div class="text-sm {row.kind === 'invite' ? 'text-gray-300 dark:text-gray-600' : 'text-gray-500'}">
					{row.kind === 'invite' ? '—' : row.memberCount}
				</div>

				<div class="text-sm text-right tabular-nums {row.kind === 'invite' ? 'text-gray-300 dark:text-gray-600' : ''}">
					{row.kind === 'invite' ? '—' : formatUsd(row.usage?.cost_usd ?? 0, '$0.00')}
				</div>
				<div class="text-sm text-right tabular-nums">
					{row.kind === 'invite'
						? formatUsd(row.invite.monthly_limit_usd, $i18n.t('Unlimited'))
						: formatUsd(row.monthly_limit_usd, $i18n.t('Unlimited'))}
				</div>
				<div class="text-sm text-right tabular-nums {row.kind === 'invite' ? 'text-gray-300 dark:text-gray-600' : 'text-gray-500'}">
					{row.kind === 'invite'
						? '—'
						: row.monthly_limit_usd == null
							? '—'
							: formatUsd(remainingUsd(row.monthly_limit_usd, row.usage?.cost_usd ?? 0))}
				</div>
				{#if row.kind === 'invite'}
					<div class="text-[11px] text-gray-300 dark:text-gray-600">—</div>
				{:else}
				<Tooltip content={tokenUsageTooltip(row.usage)} className="min-w-0 block">
					<div class="text-[11px] text-gray-500 tabular-nums truncate">
						{tokenLine(row.usage)}
					</div>
				</Tooltip>
				{/if}

				<div class="flex justify-center">
					{#if row.kind !== 'platform' && row.kind !== 'invite'}
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
					{#if row.kind !== 'platform' && row.kind !== 'invite'}
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
					{#if row.kind !== 'platform' && row.kind !== 'invite'}
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

				<div class="flex justify-end items-center gap-1 shrink-0 flex-wrap">
					{#if row.kind === 'invite'}
						<button
							class="text-xs px-2 py-1.5 rounded-lg bg-gray-900 text-white dark:bg-white dark:text-gray-900 whitespace-nowrap"
							type="button"
							on:click={() => resendInvite(row.invite.id)}
						>
							{$i18n.t('Resend')}
						</button>
						<button
							class="text-xs px-2 py-1.5 rounded-lg text-red-600 hover:bg-red-50 dark:hover:bg-red-950 whitespace-nowrap"
							type="button"
							on:click={() => cancelInvite(row.invite.id)}
						>
							{$i18n.t('Cancel')}
						</button>
					{:else if row.kind === 'workspace' && row.active === false}
						<button
							class="text-xs px-2 py-1.5 rounded-lg bg-gray-900 text-white dark:bg-white dark:text-gray-900 disabled:opacity-50 whitespace-nowrap"
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

			{#if row.kind !== 'personal' && row.kind !== 'invite' && expandedId === row.id}
				<div class="ml-10 mt-1 mb-2 rounded-lg bg-gray-50 dark:bg-gray-850/60 px-3 py-2">
					<div class="flex justify-end py-1">
						<button
							class="px-2.5 py-1.5 rounded-lg bg-gray-900 text-white dark:bg-white dark:text-gray-900 transition font-medium text-xs flex items-center gap-1.5"
							type="button"
							on:click={() => {
								showAddMember = !showAddMember;
								if (showAddMember) {
									memberUserId = '';
									memberRole = row.kind === 'platform' ? 'admin' : 'user';
								}
							}}
						>
							<svg
								xmlns="http://www.w3.org/2000/svg"
								viewBox="0 0 20 20"
								fill="currentColor"
								class="size-4"
							>
								<path
									d="M10.75 4.75a.75.75 0 0 0-1.5 0v4.5h-4.5a.75.75 0 0 0 0 1.5h4.5v4.5a.75.75 0 0 0 1.5 0v-4.5h4.5a.75.75 0 0 0 0-1.5h-4.5v-4.5Z"
								/>
							</svg>
							{$i18n.t('Add a user')}
						</button>
					</div>
					{#if showAddMember}
					<form
						class="flex flex-wrap items-center gap-2 py-1.5"
						on:submit|preventDefault={() => addExistingMember(row)}
					>
						<select
							class="min-w-[14rem] flex-1 text-sm py-1.5 px-2 rounded-lg bg-white dark:bg-gray-900 outline-hidden"
							bind:value={memberUserId}
						>
							<option value="">{$i18n.t('Add an existing user')}</option>
							{#each candidatesFor(row) as person (person.id)}
								<option value={person.id}>
									{person.name}{person.email ? ` (${person.email})` : ''}
								</option>
							{/each}
						</select>
						{#if row.kind !== 'platform'}
							<select
								class="text-sm py-1.5 px-2 rounded-lg bg-white dark:bg-gray-900 outline-hidden"
								bind:value={memberRole}
							>
								<option value="user">{$i18n.t('User')}</option>
								<option value="admin">{$i18n.t('Admin')}</option>
							</select>
						{:else}
							<span class="text-xs text-gray-500">{$i18n.t('Admin')}</span>
						{/if}
						<button
							class="text-xs px-2.5 py-1.5 rounded-lg bg-gray-900 text-white dark:bg-white dark:text-gray-900 disabled:opacity-50"
							type="submit"
							disabled={addingMember || !memberUserId}
						>
							{$i18n.t('Add')}
						</button>
					</form>
					{/if}
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
								<div class="flex items-center gap-1 shrink-0">
									<div class="text-xs text-gray-500 capitalize">{member.role}</div>
									{#if member.role !== 'owner' || (row.members ?? []).filter((item) => item.role === 'owner').length > 1}
										<Tooltip content={$i18n.t('Remove from organization')}>
											<button
												class="self-center w-fit text-sm p-1 hover:bg-black/5 dark:hover:bg-white/5 rounded-lg text-gray-400 hover:text-red-600"
												type="button"
												on:click={() => askRemoveMember(row, member)}
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
								</div>
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
	.org-table {
		width: 100%;
		min-width: 71.5rem;
	}

	.org-table-row {
		grid-template-columns:
			minmax(12rem, 1.8fr)
			7.5rem
			3.75rem
			4.5rem
			5.5rem
			5rem
			minmax(6rem, 1fr)
			4rem
			4rem
			4.25rem
			6.5rem;
	}

	.org-table-row > :global(*) {
		min-width: 0;
	}

	.type-tags :global(div) {
		max-width: 100%;
		white-space: normal;
		overflow: visible;
		display: inline-block;
		-webkit-line-clamp: unset;
	}
</style>
