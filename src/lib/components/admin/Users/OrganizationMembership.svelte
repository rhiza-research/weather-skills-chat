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
	import Badge from '$lib/components/common/Badge.svelte';
	import Plus from '$lib/components/icons/Plus.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';

	const i18n = getContext('i18n');

	export let title = '';
	export let organizationId = '';

	let org = null;
	let loading = false;
	let query = '';
	let results = [];
	let showAdd = false;
	let searchInput;

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

	<div class="flex items-center gap-3 justify-between text-xs uppercase px-1 font-bold">
		<div class="w-full">{$i18n.t('Member')}</div>
		<div class="w-full">{$i18n.t('Role')}</div>
		<div class="w-full"></div>
	</div>
	<hr class="mt-1.5 border-gray-100 dark:border-gray-850" />

	{#each org.members ?? [] as member (member.user_id)}
		<div class="flex items-center gap-3 justify-between px-1 py-2 text-sm">
			<div class="flex items-center gap-2.5 w-full min-w-0">
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
			<div class="w-full">
				{#if isAtLeastAdmin}
					<select
						class="bg-transparent text-sm pr-8 outline-hidden cursor-pointer w-fit"
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
			<div class="w-full flex justify-end">
				{#if isAtLeastAdmin}
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
{/if}
