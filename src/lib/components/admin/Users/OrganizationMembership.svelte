<script lang="ts">
	import { getContext } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { organizations, activeOrganizationId, user } from '$lib/stores';
	import {
		addOrganizationMember,
		getOrganizationById,
		removeOrganizationMember,
		updateOrganizationMemberRole
	} from '$lib/apis/organizations';
	import { searchUsers } from '$lib/apis/users';
	import {
		createOrganizationInvitation,
		getOrganizationInvitations,
		resendOrganizationInvitation,
		cancelOrganizationInvitation
	} from '$lib/apis/invitations';
	import { WEBUI_BASE_URL } from '$lib/constants';
	import { formatTokenCount, formatUsd, remainingUsd, tokenUsageLabel, tokenUsageTooltip } from '$lib/utils/usage';
	import Badge from '$lib/components/common/Badge.svelte';
	import Modal from '$lib/components/common/Modal.svelte';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import EditMemberLimitModal from '$lib/components/admin/Users/UserList/EditMemberLimitModal.svelte';

	const i18n = getContext('i18n');

	export let title = '';
	export let organizationId = '';

	let org = null;
	let loading = false;
	let showInvite = false;
	let inviteEmail = '';
	let inviteLimit = 300;
	let inviteUnlimited = true;
	let inviteRole = 'user';
	let inviting = false;
	let showAdd = false;
	let addQuery = '';
	let addResults = [];
	let addUserId = '';
	let addRole = 'user';
	let adding = false;
	let addSearchTimer;
	let invitations = [];
	let search = '';
	let showEditLimitModal = false;
	let showRemoveConfirm = false;
	let pendingRemove = null;
	let selectedMember = null;

	$: current = ($organizations ?? []).find((item) => item.id === $activeOrganizationId);
	$: targetOrgId = organizationId || $activeOrganizationId || $user?.id;
	$: isPersonal =
		!organizationId &&
		(current?.kind === 'personal' ||
			!$activeOrganizationId ||
			$activeOrganizationId === $user?.id);
	$: isPlatform = (organizationId || current?.id || $activeOrganizationId) === 'platform';
	$: isAtLeastAdmin = org?.role === 'owner' || org?.role === 'admin';
	$: isOwner = org?.role === 'owner';

	const load = async () => {
		const id = targetOrgId;
		if (!id) {
			org = null;
			return;
		}
		loading = true;
		try {
			org = await getOrganizationById(localStorage.token, id);
		} catch (error) {
			toast.error(`${error}`);
			org = null;
		}
		loading = false;
		await loadInvitations();
	};

	const loadInvitations = async () => {
		const id = targetOrgId;
		if (!id || isPersonal) {
			invitations = [];
			return;
		}
		try {
			invitations = await getOrganizationInvitations(localStorage.token, id);
		} catch (error) {
			invitations = [];
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

	const openInvite = () => {
		inviteEmail = '';
		inviteUnlimited = true;
		inviteLimit = 300;
		inviteRole = isPlatform ? 'admin' : 'user';
		showInvite = true;
	};

	const openAdd = () => {
		addQuery = '';
		addResults = [];
		addUserId = '';
		addRole = isPlatform ? 'admin' : 'user';
		showAdd = true;
	};

	const searchExisting = async () => {
		const query = addQuery.trim();
		if (query.length < 2) {
			addResults = [];
			return;
		}
		try {
			const found = (await searchUsers(localStorage.token, query)) ?? [];
			const memberIds = new Set((org?.members ?? []).map((member) => member.user_id));
			addResults = found.filter((person) => person?.id && !memberIds.has(person.id));
			if (!addResults.some((person) => person.id === addUserId)) {
				addUserId = '';
			}
		} catch (error) {
			toast.error(`${error}`);
			addResults = [];
		}
	};

	const onAddQuery = () => {
		clearTimeout(addSearchTimer);
		addSearchTimer = setTimeout(searchExisting, 200);
	};

	const addExistingMember = async () => {
		if (!org || !addUserId) return;
		const role = isPlatform ? 'admin' : addRole;
		adding = true;
		try {
			await addOrganizationMember(localStorage.token, org.id, addUserId, role);
			showAdd = false;
			toast.success($i18n.t('Member added'));
			await load();
		} catch (error) {
			toast.error(`${error}`);
		}
		adding = false;
	};

	const sendInvite = async () => {
		if (!org || !inviteEmail.trim()) return;
		const monthlyLimit = inviteLimitValue();
		if (monthlyLimit === undefined) return;
		inviting = true;
		try {
			await createOrganizationInvitation(
				localStorage.token,
				org.id,
				inviteEmail.trim(),
				monthlyLimit,
				isPlatform ? 'admin' : inviteRole
			);
			inviteEmail = '';
			showInvite = false;
			toast.success($i18n.t('Invitation sent'));
			await loadInvitations();
		} catch (error) {
			toast.error(`${error}`);
		}
		inviting = false;
	};

	const resendInvite = async (id) => {
		if (!org) return;
		try {
			await resendOrganizationInvitation(localStorage.token, org.id, id);
			toast.success($i18n.t('Invitation resent'));
			await loadInvitations();
		} catch (error) {
			toast.error(`${error}`);
		}
	};

	const cancelInvite = async (id) => {
		if (!org) return;
		try {
			await cancelOrganizationInvitation(localStorage.token, org.id, id);
			toast.success($i18n.t('Invitation canceled'));
			await loadInvitations();
		} catch (error) {
			toast.error(`${error}`);
		}
	};

	const changeRole = async (userId: string, role: string) => {
		if (!org) return;
		try {
			org = await updateOrganizationMemberRole(localStorage.token, org.id, userId, role);
		} catch (error) {
			toast.error(`${error}`);
			await load();
		}
	};

	const askRemove = (member) => {
		pendingRemove = member;
		showRemoveConfirm = true;
	};

	const confirmRemove = async () => {
		if (!org || !pendingRemove) return;
		try {
			org = await removeOrganizationMember(localStorage.token, org.id, pendingRemove.user_id);
		} catch (error) {
			toast.error(`${error}`);
		}
		pendingRemove = null;
	};

	const openLimitEditor = (member) => {
		selectedMember = member;
		showEditLimitModal = true;
	};

	$: tableRows = [
		...(org?.members ?? []).map((member) => ({
			kind: 'member',
			id: member.user_id,
			member
		})),
		...(isAtLeastAdmin ? invitations : []).map((invite) => ({
			kind: 'invite',
			id: `invite:${invite.id}`,
			invite
		}))
	].filter((row) => {
		if (!search.trim()) return true;
		const q = search.toLowerCase();
		if (row.kind === 'invite') {
			return (row.invite.email || '').toLowerCase().includes(q);
		}
		return (
			(row.member.name || '').toLowerCase().includes(q) ||
			(row.member.email || '').toLowerCase().includes(q)
		);
	});

	const tokenLine = (usage) => {
		if (!usage) return '—';
		return `${formatTokenCount(usage.prompt_tokens)} / ${formatTokenCount(usage.completion_tokens)} / ${formatTokenCount(usage.total_tokens)} / ${formatTokenCount(usage.uncached_tokens)}`;
	};

	$: if (targetOrgId !== undefined) {
		load();
	}
</script>

<div class="mt-0.5 mb-2 gap-1 flex flex-col md:flex-row justify-between">
	<div class="flex md:self-center text-lg font-medium px-0.5">
		{title || $i18n.t('Organization membership')}
		<div class="flex self-center w-[1px] h-6 mx-2.5 bg-gray-50 dark:bg-gray-850" />
		<span class="text-lg font-medium text-gray-500 dark:text-gray-300">
			{org?.name ?? current?.name ?? $i18n.t('Personal')}
		</span>
	</div>

	{#if isAtLeastAdmin && !isPersonal}
		<input
			class="text-sm py-1.5 px-3 rounded-lg bg-gray-50 dark:bg-gray-850 outline-hidden md:w-64"
			placeholder={$i18n.t('Search')}
			bind:value={search}
		/>
		<button
			class="px-3 py-1.5 rounded-lg bg-gray-50 dark:bg-gray-850 transition font-medium text-sm"
			type="button"
			on:click={openAdd}
		>
			{$i18n.t('Add existing user')}
		</button>
		<button
			class="px-3 py-1.5 rounded-lg bg-gray-900 text-white dark:bg-white dark:text-gray-900 transition font-medium text-sm flex items-center gap-1.5"
			type="button"
			on:click={openInvite}
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
	{/if}
</div>

{#if loading && !org}
	<div class="w-full h-40 flex justify-center items-center">
		<Spinner />
	</div>
{:else if isPersonal}
	<div class="text-sm text-gray-500 dark:text-gray-400 px-0.5 py-4">
		{$i18n.t('This is your personal workspace. It cannot have members or be shared.')}
	</div>
	{#if org}
		<div class="text-sm px-0.5 pb-4">
			<div class="font-medium">
				{formatUsd(org.usage?.cost_usd ?? 0, '$0.00')}
				{#if org.monthly_limit_usd == null}
					{$i18n.t('this month')}
				{:else}
					/ {formatUsd(org.monthly_limit_usd)}
					<span class="text-gray-500 font-normal">
						({formatUsd(remainingUsd(org.monthly_limit_usd, org.usage?.cost_usd ?? 0))}
						{$i18n.t('remaining')})
					</span>
				{/if}
			</div>
			<Tooltip content={tokenUsageTooltip(org.usage)} className="inline-flex mt-2">
				<div class="text-xs text-gray-500">
					{$i18n.t('Tokens')}: {tokenLine(org.usage)}
				</div>
			</Tooltip>
		</div>
	{/if}
{:else if org}
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
						{$i18n.t('No limit')}
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
					{#if org?.monthly_limit_usd != null}
						<div class="text-xs text-gray-500 mt-2">
							{$i18n.t('Cannot exceed the organization monthly usage limit of {{limit}}.', {
								limit: formatUsd(org.monthly_limit_usd)
							})}
						</div>
					{/if}
				</div>
				{#if !isPlatform}
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
				{:else}
					<div class="text-xs text-gray-500">{$i18n.t('Platform organization members are admins.')}</div>
				{/if}
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

	<Modal bind:show={showAdd} size="sm">
		<div>
			<div class="flex justify-between dark:text-gray-300 px-5 pt-4 pb-2">
				<div class="text-lg font-medium self-center">{$i18n.t('Add existing user')}</div>
				<button
					class="self-center"
					type="button"
					on:click={() => {
						showAdd = false;
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
			<form class="flex flex-col gap-3 p-5" on:submit|preventDefault={addExistingMember}>
				<input
					class="w-full text-sm py-2 px-3 rounded-lg bg-gray-50 dark:bg-gray-850 outline-hidden"
					type="search"
					placeholder={$i18n.t('Search by name')}
					bind:value={addQuery}
					on:input={onAddQuery}
				/>
				<select
					class="w-full text-sm py-2 px-3 rounded-lg bg-gray-50 dark:bg-gray-850 outline-hidden"
					bind:value={addUserId}
					required
				>
					<option value="">{$i18n.t('Select a user')}</option>
					{#each addResults as person (person.id)}
						<option value={person.id}>{person.name}</option>
					{/each}
				</select>
				{#if !isPlatform}
					<label class="block">
						<div class="mb-1 text-xs text-gray-500">{$i18n.t('Role')}</div>
						<select
							class="w-full text-sm py-2 px-3 rounded-lg bg-gray-50 dark:bg-gray-850 outline-hidden"
							bind:value={addRole}
						>
							<option value="user">{$i18n.t('User')}</option>
							<option value="admin">{$i18n.t('Admin')}</option>
						</select>
					</label>
				{/if}
				<div class="flex justify-end">
					<button
						class="px-3.5 py-1.5 text-sm font-medium bg-black hover:bg-gray-900 text-white dark:bg-white dark:text-black dark:hover:bg-gray-100 transition rounded-full disabled:opacity-50"
						type="submit"
						disabled={adding || !addUserId}
					>
						{$i18n.t('Add')}
					</button>
				</div>
			</form>
		</div>
	</Modal>

	<div class="flex items-baseline gap-16 text-sm px-0.5 mb-3">
		<div>
			<span class="font-medium">
				{formatUsd(org.usage?.cost_usd ?? 0, '$0.00')}
				{#if org.monthly_limit_usd == null}
					{$i18n.t('this month')} ({$i18n.t('Unlimited')})
				{:else}
					/ {formatUsd(org.monthly_limit_usd)}
				{/if}
			</span>
			{#if org.monthly_limit_usd != null}
				<span class="text-gray-500">
					· {formatUsd(remainingUsd(org.monthly_limit_usd, org.usage?.cost_usd ?? 0))}
					{$i18n.t('remaining')}
				</span>
			{/if}
		</div>
		<Tooltip content={tokenUsageTooltip(org.usage)} className="inline-flex">
			<span class="text-xs text-gray-500">
				{$i18n.t('Tokens')}: {tokenLine(org.usage)}
			</span>
		</Tooltip>
	</div>

	<div class="overflow-x-auto">
	<div class="min-w-[56rem]">
	<div class="member-table-row grid items-end gap-x-3 px-1 text-xs uppercase font-bold">
		<div>{$i18n.t('Member')}</div>
		<div>{$i18n.t('Role')}</div>
		<div class="text-right">{$i18n.t('Used')}</div>
		<div class="text-right">{$i18n.t('Monthly usage limit')}</div>
		<div class="text-right whitespace-nowrap">{$i18n.t('Remaining')}</div>
		<div>
			<Tooltip content={tokenUsageLabel()} className="inline-flex">
				<span>{$i18n.t('Tokens')}</span>
			</Tooltip>
		</div>
		<div></div>
	</div>
	<hr class="mt-1.5 border-gray-100 dark:border-gray-850" />

	{#each tableRows as row (row.id)}
		<div class="member-table-row grid items-center gap-x-3 px-1 py-2 text-sm">
			{#if row.kind === 'invite'}
			<div class="flex items-center gap-2.5 min-w-0">
				<div
					class="rounded-full w-6 h-6 shrink-0 bg-gray-100 dark:bg-gray-850 flex items-center justify-center text-xs text-gray-500"
				>
					+
				</div>
				<div class="min-w-0">
					<div class="font-medium truncate">{row.invite.email}</div>
					<div class="text-xs text-gray-500 truncate">
						{$i18n.t('Sent')} {new Date(row.invite.created_at * 1000).toLocaleDateString()}
						· {row.invite.expired
							? $i18n.t('Expired')
							: `${$i18n.t('Expires')} ${new Date(row.invite.expires_at * 1000).toLocaleDateString()}`}
					</div>
				</div>
			</div>
			<div>
				{$i18n.t('Invited')} · {row.invite.role === 'admin' ? $i18n.t('Admin') : $i18n.t('User')}
			</div>
			<div class="text-right text-gray-300 dark:text-gray-600">—</div>
			<div class="text-right tabular-nums">
				{formatUsd(row.invite.monthly_limit_usd, $i18n.t('No limit'))}
			</div>
			<div class="text-right text-gray-300 dark:text-gray-600">—</div>
			<div class="text-gray-300 dark:text-gray-600">—</div>
			<div class="flex justify-end items-center gap-1 flex-wrap">
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
			</div>
			{:else}
			<div class="flex items-center gap-2.5 min-w-0">
				<img
					class="rounded-full w-6 h-6 object-cover shrink-0"
					src={row.member.profile_image_url?.startsWith(WEBUI_BASE_URL) ||
					row.member.profile_image_url?.startsWith('https://www.gravatar.com/avatar/') ||
					row.member.profile_image_url?.startsWith('data:')
						? row.member.profile_image_url
						: `/user.png`}
					alt=""
				/>
				<div class="min-w-0">
					<div class="font-medium truncate">{row.member.name ?? row.member.user_id}</div>
					<div class="text-xs text-gray-500 truncate">{row.member.email ?? ''}</div>
				</div>
			</div>
			<div class="min-w-0">
				{#if isAtLeastAdmin}
					<select
						class="bg-transparent text-sm pr-8 outline-hidden cursor-pointer w-fit max-w-full"
						value={row.member.role}
						on:change={(e) => changeRole(row.member.user_id, e.currentTarget.value)}
					>
						{#if isOwner}
							<option value="owner">{$i18n.t('Owner')}</option>
						{/if}
						<option value="admin">{$i18n.t('Admin')}</option>
						{#if !isPlatform}
							<option value="user">{$i18n.t('User')}</option>
						{/if}
					</select>
				{:else}
					<Badge type="muted" content={$i18n.t(row.member.role)} />
				{/if}
			</div>
			<div class="text-right text-sm tabular-nums">
				{formatUsd(row.member.usage?.cost_usd ?? 0, '$0.00')}
			</div>
			<div class="text-right tabular-nums">
				{formatUsd(row.member.monthly_limit_usd, $i18n.t('Unlimited'))}
			</div>
			<div class="text-right text-sm tabular-nums text-gray-500">
				{row.member.monthly_limit_usd == null
					? '—'
					: formatUsd(remainingUsd(row.member.monthly_limit_usd, row.member.usage?.cost_usd ?? 0))}
			</div>
			<Tooltip content={tokenUsageTooltip(row.member.usage)} className="min-w-0 block">
				<div class="text-[11px] text-gray-500 tabular-nums truncate">
					{tokenLine(row.member.usage)}
				</div>
			</Tooltip>
			<div class="flex justify-end items-center">
				{#if isAtLeastAdmin}
					<Tooltip content={$i18n.t('Edit monthly usage limit')}>
						<button
							class="self-center w-fit text-sm px-2 py-2 hover:bg-black/5 dark:hover:bg-white/5 rounded-xl"
							on:click={() => openLimitEditor(row.member)}
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
					<button
						class="text-xs text-red-600 px-2 py-1 rounded-lg hover:bg-red-50 dark:hover:bg-red-950"
						on:click={() => askRemove(row.member)}
					>
						{$i18n.t('Remove')}
					</button>
				{/if}
			</div>
			{/if}
		</div>
	{:else}
		<div class="text-sm text-gray-500 py-6 text-center">{$i18n.t('No members yet.')}</div>
	{/each}
	</div>
	</div>
{/if}

<ConfirmDialog
	bind:show={showRemoveConfirm}
	title={$i18n.t('Remove member')}
	message={$i18n.t('Remove {{name}} from this organization?', {
		name: pendingRemove?.name || pendingRemove?.email || ''
	})}
	confirmLabel={$i18n.t('Remove')}
	onConfirm={confirmRemove}
/>

{#key selectedMember}
	<EditMemberLimitModal
		bind:show={showEditLimitModal}
		orgId={org?.id}
		member={selectedMember}
		orgLimit={org?.monthly_limit_usd}
		on:save={(e) => {
			org = e.detail;
		}}
	/>
{/key}

<style>
	.member-table-row {
		grid-template-columns:
			minmax(0, 1.5fr)
			6rem
			5rem
			7.5rem
			8.5rem
			minmax(0, 1fr)
			8.5rem;
	}

	.member-table-row > :global(*) {
		min-width: 0;
	}

	.member-table-row > :global(*:nth-child(5)) {
		padding-right: 1.75rem;
	}

	.member-table-row > :global(*:nth-child(6)) {
		padding-left: 0.75rem;
	}
</style>
