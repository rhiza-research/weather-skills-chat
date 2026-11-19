<script lang="ts">
	import PlusSolid from '$lib/components/icons/PlusSolid.svelte';
	import XMarkSolid from '$lib/components/icons/XMarkSolid.svelte';
	import PencilLine from '$lib/components/icons/PencilLine.svelte';
	import { getContext } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { organizations, activeOrganizationId, user } from '$lib/stores';
	import {
		getOrganizationById,
		removeOrganizationMember,
		updateOrganizationMemberRole
	} from '$lib/apis/organizations';
	import {
		createOrganizationInvitation,
		getOrganizationInvitations,
		resendOrganizationInvitation,
		cancelOrganizationInvitation
	} from '$lib/apis/invitations';
	import { WEBUI_BASE_URL } from '$lib/constants';
	import {
		formatCreditAmount,
		formatTokenCount,
		formatUsd,
		remainingUsd,
		tokenUsageLabel,
		tokenUsageTooltip
	} from '$lib/utils/usage';
	import Badge from '$lib/components/common/Badge.svelte';
	import Modal from '$lib/components/common/Modal.svelte';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import EditMemberLimitModal from '$lib/components/admin/Users/UserList/EditMemberLimitModal.svelte';

	const i18n = getContext('i18n');

	export let title = '';
	export let organizationId = '';
	export let credits = false;

	const usageAmount = (n, fallback = '—') =>
		credits ? formatCreditAmount(n, fallback) : formatUsd(n, fallback);

	let org = null;
	let loading = false;
	let showInvite = false;
	let inviteEmail = '';
	let inviteLimit = 300;
	let inviteUnlimited = true;
	let inviteRole = 'user';
	let inviting = false;
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
		<div class="flex self-center w-[1px] h-6 mx-2.5 bg-surface" />
		<span class="text-lg font-medium text-body">
			{org?.name ?? current?.name ?? $i18n.t('Personal')}
		</span>
	</div>

	{#if isAtLeastAdmin && !isPersonal}
		<input
			class="field md:w-64"
			placeholder={$i18n.t('Search')}
			bind:value={search}
		/>
		<button
			class="px-3 py-1.5 rounded-lg bg-inverse text-on-inverse transition font-medium text-sm flex items-center gap-1.5"
			type="button"
			on:click={openInvite}
		>
			<PlusSolid className="size-4" />
			{$i18n.t('Invite a user')}
		</button>
	{/if}
</div>

{#if loading && !org}
	<div class="w-full h-40 flex justify-center items-center">
		<Spinner />
	</div>
{:else if isPersonal}
	<div class="text-sm text-muted px-0.5 py-4">
		{$i18n.t('This is your personal workspace. It cannot have members or be shared.')}
	</div>
	{#if org}
		<div class="text-sm px-0.5 pb-4">
			<div class="font-medium">
				{usageAmount(org.usage?.cost_usd ?? 0, credits ? '0.00' : '$0.00')}
				{#if org.monthly_limit_usd == null}
					{#if credits}{' '}{$i18n.t('credits')}{/if}
					{$i18n.t('this month')}
				{:else}
					/ {usageAmount(org.monthly_limit_usd)}
					{#if credits}{' '}{$i18n.t('credits')}{/if}
					<span class="text-muted font-normal">
						({usageAmount(remainingUsd(org.monthly_limit_usd, org.usage?.cost_usd ?? 0))}
						{$i18n.t(credits ? 'remaining credits' : 'remaining')})
					</span>
				{/if}
			</div>
			<Tooltip content={tokenUsageTooltip(org.usage)} className="inline-flex mt-2">
				<div class="text-xs text-muted">
					{$i18n.t('Tokens')}: {tokenLine(org.usage)}
				</div>
			</Tooltip>
		</div>
	{/if}
{:else if org}
	<Modal bind:show={showInvite} size="sm">
		<div>
			<div class="flex justify-between dark:text-gray-300 px-5 pt-4 pb-2">
				<h2 class="text-lg font-medium self-center">{$i18n.t('Invite a user')}</h2>
				<button
					class="self-center"
					type="button"
					on:click={() => {
						showInvite = false;
					}}
				>
					<XMarkSolid className="size-5" />
				</button>
			</div>
			<hr class="border-line my-2" />
			<form class="flex flex-col gap-3 p-5" on:submit|preventDefault={sendInvite}>
				<input
					class="field"
					type="email"
					required
					placeholder={$i18n.t('Email')}
					bind:value={inviteEmail}
				/>
				<div>
					<div class="mb-1 text-xs text-muted">{$i18n.t('Monthly usage limit')}</div>
					<label class="flex items-center gap-2 text-sm">
						<input type="checkbox" bind:checked={inviteUnlimited} />
						{$i18n.t('No limit')}
					</label>
					{#if !inviteUnlimited}
						<div class="flex items-center gap-1.5 mt-2">
							{#if !credits}
								<span class="text-sm text-muted">$</span>
							{/if}
							<input
								class="field"
								type="number"
								min="0"
								step="0.01"
								bind:value={inviteLimit}
							/>
							{#if credits}
								<span class="text-sm text-muted">{$i18n.t('credits')}</span>
							{/if}
						</div>
					{/if}
					{#if org?.monthly_limit_usd != null}
						<div class="text-xs text-muted mt-2">
							{$i18n.t('Cannot exceed the organization monthly usage limit of {{limit}}.', {
								limit: credits
									? `${usageAmount(org.monthly_limit_usd)} ${$i18n.t('credits')}`
									: formatUsd(org.monthly_limit_usd)
							})}
						</div>
					{/if}
				</div>
				{#if !isPlatform}
					<label class="block">
						<div class="mb-1 text-xs text-muted">{$i18n.t('Role')}</div>
						<select
							class="field"
							bind:value={inviteRole}
						>
							<option value="user">{$i18n.t('User')}</option>
							<option value="admin">{$i18n.t('Admin')}</option>
						</select>
					</label>
				{:else}
					<div class="text-xs text-muted">{$i18n.t('Platform organization members are admins.')}</div>
				{/if}
				<div class="flex justify-end">
					<button
						class="px-4 py-1.5 text-sm font-medium bg-inverse hover:bg-gray-900 text-on-inverse dark:hover:bg-gray-100 transition rounded-full disabled:opacity-50"
						type="submit"
						disabled={inviting}
					>
						{$i18n.t('Send invite')}
					</button>
				</div>
			</form>
		</div>
	</Modal>

	<div class="flex items-baseline gap-16 text-sm px-0.5 mb-3">
		<div>
			<span class="font-medium">
				{usageAmount(org.usage?.cost_usd ?? 0, credits ? '0.00' : '$0.00')}
				{#if org.monthly_limit_usd == null}
					{#if credits}{' '}{$i18n.t('credits')}{/if}
					{$i18n.t('this month')} ({$i18n.t('Unlimited')})
				{:else}
					/ {usageAmount(org.monthly_limit_usd)}
					{#if credits}{' '}{$i18n.t('credits')}{/if}
				{/if}
			</span>
			{#if org.monthly_limit_usd != null}
				<span class="text-muted">
					· {usageAmount(remainingUsd(org.monthly_limit_usd, org.usage?.cost_usd ?? 0))}
					{$i18n.t(credits ? 'remaining credits' : 'remaining')}
				</span>
			{/if}
		</div>
		<Tooltip content={tokenUsageTooltip(org.usage)} className="inline-flex">
			<span class="text-xs text-muted">
				{$i18n.t('Tokens')}: {tokenLine(org.usage)}
			</span>
		</Tooltip>
	</div>

	<div class="overflow-x-auto">
	<div class="min-w-[56rem]">
	<div
		class="member-table-row grid items-end gap-x-3 px-1 text-xs font-semibold text-muted"
	>
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
	<hr class="border-line my-2 mt-1.5" />

	{#each tableRows as row (row.id)}
		<div class="member-table-row grid items-center gap-x-3 px-1 py-2 text-sm">
			{#if row.kind === 'invite'}
			<div class="flex items-center gap-2.5 min-w-0">
				<div
					class="rounded-full size-6 shrink-0 bg-surface flex items-center justify-center text-xs text-muted"
				>
					+
				</div>
				<div class="min-w-0">
					<div class="font-medium truncate">{row.invite.email}</div>
					<div class="text-xs text-muted truncate">
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
			<div class="text-right text-muted">—</div>
			<div class="text-right tabular-nums">
				{usageAmount(row.invite.monthly_limit_usd, $i18n.t('No limit'))}{#if credits && row.invite.monthly_limit_usd != null}{' '}{$i18n.t('credits')}{/if}
			</div>
			<div class="text-right text-muted">—</div>
			<div class="text-muted">—</div>
			<div class="flex justify-end items-center gap-1 flex-wrap">
				<button
					class="text-xs px-2 py-1.5 rounded-lg bg-inverse text-on-inverse whitespace-nowrap"
					type="button"
					on:click={() => resendInvite(row.invite.id)}
				>
					{$i18n.t('Resend')}
				</button>
				<button
					class="text-xs px-2 py-1.5 rounded-xl text-red-600 hover:bg-red-50 dark:hover:bg-red-950 whitespace-nowrap"
					type="button"
					on:click={() => cancelInvite(row.invite.id)}
				>
					{$i18n.t('Cancel')}
				</button>
			</div>
			{:else}
			<div class="flex items-center gap-2.5 min-w-0">
				<img
					class="rounded-full size-6 object-cover shrink-0"
					src={row.member.profile_image_url?.startsWith(WEBUI_BASE_URL) ||
					row.member.profile_image_url?.startsWith('https://www.gravatar.com/avatar/') ||
					row.member.profile_image_url?.startsWith('data:')
						? row.member.profile_image_url
						: `/user.png`}
					alt=""
				/>
				<div class="min-w-0">
					<div class="font-medium truncate">{row.member.name ?? row.member.user_id}</div>
					<div class="text-xs text-muted truncate">{row.member.email ?? ''}</div>
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
				{usageAmount(row.member.usage?.cost_usd ?? 0, credits ? '0.00' : '$0.00')}{#if credits}{' '}{$i18n.t('credits')}{/if}
			</div>
			<div class="text-right tabular-nums">
				{usageAmount(row.member.monthly_limit_usd, $i18n.t('Unlimited'))}{#if credits && row.member.monthly_limit_usd != null}{' '}{$i18n.t('credits')}{/if}
			</div>
			<div class="text-right text-sm tabular-nums text-muted">
				{row.member.monthly_limit_usd == null
					? '—'
					: usageAmount(remainingUsd(row.member.monthly_limit_usd, row.member.usage?.cost_usd ?? 0))}{#if credits && row.member.monthly_limit_usd != null}{' '}{$i18n.t('credits')}{/if}
			</div>
			<Tooltip content={tokenUsageTooltip(row.member.usage)} className="min-w-0 block">
				<div class="text-xs text-muted tabular-nums truncate">
					{tokenLine(row.member.usage)}
				</div>
			</Tooltip>
			<div class="flex justify-end items-center">
				{#if isAtLeastAdmin}
					<Tooltip content={$i18n.t('Edit monthly usage limit')}>
						<button
							class="btn-ghost"
							on:click={() => openLimitEditor(row.member)}
						>
							<PencilLine className="size-4" />
						</button>
					</Tooltip>
					<button
						class="text-xs text-red-600 px-2 py-1 rounded-xl hover:bg-red-50 dark:hover:bg-red-950"
						on:click={() => askRemove(row.member)}
					>
						{$i18n.t('Remove')}
					</button>
				{/if}
			</div>
			{/if}
		</div>
	{:else}
		<div class="text-sm text-muted py-6 text-center">{$i18n.t('No members yet.')}</div>
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
		{credits}
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
