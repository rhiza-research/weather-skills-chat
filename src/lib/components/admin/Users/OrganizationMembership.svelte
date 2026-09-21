<script lang="ts">
	import { getContext, tick } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { organizations, activeOrganizationId, user } from '$lib/stores';
	import {
		addOrganizationMember,
		getOrganizationById,
		getOrganizations,
		removeOrganizationMember,
		updateOrganizationMemberRole
	} from '$lib/apis/organizations';
	import { searchUsers } from '$lib/apis/users';
	import { WEBUI_BASE_URL } from '$lib/constants';
	import { formatTokenCount, formatUsd, remainingUsd, tokenUsageLabel, tokenUsageTooltip } from '$lib/utils/usage';
	import Badge from '$lib/components/common/Badge.svelte';
	import Plus from '$lib/components/icons/Plus.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import EditMemberLimitModal from '$lib/components/admin/Users/UserList/EditMemberLimitModal.svelte';

	const i18n = getContext('i18n');

	export let title = '';
	export let organizationId = '';

	let org = null;
	let loading = false;
	let query = '';
	let results = [];
	let showAdd = false;
	let searchInput;
	let showEditLimitModal = false;
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
	};

	const search = async () => {
		if (!query.trim()) {
			results = [];
			return;
		}
		try {
			const memberIds = new Set((org?.members ?? []).map((member) => member.user_id));
			results = (await searchUsers(localStorage.token, query.trim())).filter(
				(result) => !memberIds.has(result.id)
			);
		} catch (error) {
			toast.error(`${error}`);
		}
	};

	const openAdd = async () => {
		showAdd = !showAdd;
		if (showAdd) {
			await tick();
			searchInput?.focus();
		} else {
			query = '';
			results = [];
		}
	};

	const add = async (userId: string) => {
		if (!org) return;
		try {
			org = await addOrganizationMember(
				localStorage.token,
				org.id,
				userId,
				isPlatform ? 'admin' : 'user'
			);
			query = '';
			results = [];
			showAdd = false;
			organizations.set(await getOrganizations(localStorage.token));
			toast.success($i18n.t('Member added'));
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

	const remove = async (userId: string) => {
		if (!org) return;
		try {
			org = await removeOrganizationMember(localStorage.token, org.id, userId);
		} catch (error) {
			toast.error(`${error}`);
		}
	};

	const openLimitEditor = (member) => {
		selectedMember = member;
		showEditLimitModal = true;
	};

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
		<Tooltip content={$i18n.t('Add member')}>
			<button
				class="p-2 rounded-xl hover:bg-gray-100 dark:bg-gray-900 dark:hover:bg-gray-850 transition font-medium text-sm flex items-center space-x-1"
				aria-label={$i18n.t('Add member')}
				on:click={openAdd}
			>
				<Plus className="size-3.5" />
			</button>
		</Tooltip>
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
	{#if isAtLeastAdmin && showAdd}
		<div class="mb-4">
			<input
				bind:this={searchInput}
				class="w-full text-sm py-1.5 px-0 outline-hidden bg-transparent"
				placeholder={$i18n.t('Search users to add')}
				bind:value={query}
				on:input={search}
			/>
			{#if results.length}
				<div class="mt-1 rounded-lg border border-gray-100 dark:border-gray-850 overflow-hidden">
					{#each results as result}
						<button
							class="w-full text-left px-3 py-2 text-sm hover:bg-gray-50 dark:hover:bg-gray-850 flex items-center gap-2"
							on:click={() => add(result.id)}
						>
							<img
								class="rounded-full w-6 h-6 object-cover"
								src={result.profile_image_url?.startsWith(WEBUI_BASE_URL) ||
								result.profile_image_url?.startsWith('https://www.gravatar.com/avatar/') ||
								result.profile_image_url?.startsWith('data:')
									? result.profile_image_url
									: `/user.png`}
								alt=""
							/>
							<span class="font-medium">{result.name}</span>
							<span class="text-gray-500">· {result.email}</span>
						</button>
					{/each}
				</div>
			{:else if query.trim()}
				<div class="text-xs text-gray-500 py-2">{$i18n.t('No matching users.')}</div>
			{/if}
		</div>
	{/if}

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

	{#each org.members ?? [] as member (member.user_id)}
		<div class="member-table-row grid items-center gap-x-3 px-1 py-2 text-sm">
			<div class="flex items-center gap-2.5 min-w-0">
				<img
					class="rounded-full w-6 h-6 object-cover shrink-0"
					src={member.profile_image_url?.startsWith(WEBUI_BASE_URL) ||
					member.profile_image_url?.startsWith('https://www.gravatar.com/avatar/') ||
					member.profile_image_url?.startsWith('data:')
						? member.profile_image_url
						: `/user.png`}
					alt=""
				/>
				<div class="min-w-0">
					<div class="font-medium truncate">{member.name ?? member.user_id}</div>
					<div class="text-xs text-gray-500 truncate">{member.email ?? ''}</div>
				</div>
			</div>
			<div class="min-w-0">
				{#if isAtLeastAdmin}
					<select
						class="bg-transparent text-sm pr-8 outline-hidden cursor-pointer w-fit max-w-full"
						value={member.role}
						on:change={(e) => changeRole(member.user_id, e.currentTarget.value)}
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
					<Badge type="muted" content={$i18n.t(member.role)} />
				{/if}
			</div>
			<div class="text-right text-sm tabular-nums">
				{formatUsd(member.usage?.cost_usd ?? 0, '$0.00')}
			</div>
			<div class="text-right tabular-nums">
				{formatUsd(member.monthly_limit_usd, $i18n.t('Unlimited'))}
			</div>
			<div class="text-right text-sm tabular-nums text-gray-500">
				{member.monthly_limit_usd == null
					? '—'
					: formatUsd(remainingUsd(member.monthly_limit_usd, member.usage?.cost_usd ?? 0))}
			</div>
			<Tooltip content={tokenUsageTooltip(member.usage)} className="min-w-0 block">
				<div class="text-[11px] text-gray-500 tabular-nums truncate">
					{tokenLine(member.usage)}
				</div>
			</Tooltip>
			<div class="flex justify-end items-center">
				{#if isAtLeastAdmin}
					<Tooltip content={$i18n.t('Edit monthly usage limit')}>
						<button
							class="self-center w-fit text-sm px-2 py-2 hover:bg-black/5 dark:hover:bg-white/5 rounded-xl"
							on:click={() => openLimitEditor(member)}
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
						on:click={() => remove(member.user_id)}
					>
						{$i18n.t('Remove')}
					</button>
				{/if}
			</div>
		</div>
	{:else}
		<div class="text-sm text-gray-500 py-6 text-center">{$i18n.t('No members yet.')}</div>
	{/each}
	</div>
	</div>
{/if}

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
			7.5rem;
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
