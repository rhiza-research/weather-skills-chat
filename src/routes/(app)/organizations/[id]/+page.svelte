<script lang="ts">
	import { onMount, getContext } from 'svelte';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { toast } from 'svelte-sonner';
	import { models, organizations, user, WEBUI_NAME, showSidebar } from '$lib/stores';
	import {
		addOrganizationMember,
		deleteOrganizationById,
		getOrganizationById,
		getOrganizations,
		removeOrganizationMember,
		updateOrganizationById,
		updateOrganizationMemberRole
	} from '$lib/apis/organizations';
	import { searchUsers } from '$lib/apis/users';
	import MenuLines from '$lib/components/icons/MenuLines.svelte';

	const i18n = getContext('i18n');

	let org = null;
	let query = '';
	let results = [];
	let name = '';
	let description = '';
	let defaultModelId = '';

	$: id = $page.params.id;
	$: isPersonal = org?.kind === 'personal';
	$: isPlatform = org?.kind === 'platform';
	$: isAtLeastAdmin = org?.role === 'owner' || org?.role === 'admin';
	$: isOwner = org?.role === 'owner';

	const load = async () => {
		try {
			org = await getOrganizationById(localStorage.token, id);
			name = org.name;
			description = org.description ?? '';
			defaultModelId = (org.default_models || '').split(',')[0]?.trim() ?? '';
		} catch (error) {
			toast.error(`${error}`);
			goto('/organizations');
		}
	};

	const save = async () => {
		try {
			org = await updateOrganizationById(localStorage.token, id, {
				name,
				description,
				default_models: defaultModelId || ''
			});
			organizations.set(await getOrganizations(localStorage.token));
			toast.success($i18n.t('Organization updated'));
		} catch (error) {
			toast.error(`${error}`);
		}
	};

	const search = async () => {
		if (!query.trim()) {
			results = [];
			return;
		}
		try {
			results = await searchUsers(localStorage.token, query.trim());
		} catch (error) {
			toast.error(`${error}`);
		}
	};

	const add = async (userId: string) => {
		try {
			org = await addOrganizationMember(
				localStorage.token,
				id,
				userId,
				isPlatform ? 'admin' : 'user'
			);
			query = '';
			results = [];
			organizations.set(await getOrganizations(localStorage.token));
		} catch (error) {
			toast.error(`${error}`);
		}
	};

	const changeRole = async (userId: string, role: string) => {
		try {
			org = await updateOrganizationMemberRole(localStorage.token, id, userId, role);
		} catch (error) {
			toast.error(`${error}`);
		}
	};

	const remove = async (userId: string) => {
		try {
			org = await removeOrganizationMember(localStorage.token, id, userId);
			if (userId === $user?.id) {
				organizations.set(await getOrganizations(localStorage.token));
				goto('/organizations');
			}
		} catch (error) {
			toast.error(`${error}`);
		}
	};

	const destroy = async () => {
		if (!confirm($i18n.t('Delete this organization?'))) return;
		try {
			await deleteOrganizationById(localStorage.token, id);
			organizations.set(await getOrganizations(localStorage.token));
			goto('/organizations');
		} catch (error) {
			toast.error(`${error}`);
		}
	};

	onMount(load);
	$: if (id) load();
</script>

<svelte:head>
	<title>{org?.name ?? $i18n.t('Organization')} | {$WEBUI_NAME}</title>
</svelte:head>

<div class="flex flex-col w-full h-screen max-h-[100dvh]">
	<nav class="px-2.5 pt-1 backdrop-blur-xl">
		<div class="flex items-center gap-1">
			<div class="{$showSidebar ? 'md:hidden' : ''} self-center flex flex-none items-center">
				<button
					class="cursor-pointer p-1.5 flex rounded-xl hover:bg-gray-100 dark:hover:bg-gray-850 transition"
					on:click={() => showSidebar.set(!$showSidebar)}
				>
					<MenuLines />
				</button>
			</div>
			<a class="text-sm text-gray-500 px-1.5" href="/organizations">{$i18n.t('Organizations')}</a>
			<div class="text-lg font-medium">{org?.name ?? ''}</div>
		</div>
	</nav>

	{#if org}
		<div class="flex-1 overflow-y-auto px-4 py-4 max-w-3xl w-full mx-auto flex flex-col gap-6">
			{#if isPersonal}
				<div class="text-sm text-gray-500">
					{$i18n.t('This is your personal workspace. It cannot have members or be shared.')}
				</div>
			{:else if isAtLeastAdmin}
				<div class="rounded-xl border border-gray-100 dark:border-gray-850 p-4 flex flex-col gap-2">
					<input
						class="w-full rounded-lg bg-gray-50 dark:bg-gray-850 px-3 py-2 text-sm outline-hidden"
						bind:value={name}
					/>
					<textarea
						class="w-full rounded-lg bg-gray-50 dark:bg-gray-850 px-3 py-2 text-sm outline-hidden"
						rows="2"
						bind:value={description}
					/>
					<div>
						<div class="text-xs text-gray-500 mb-1">{$i18n.t('Default Model')}</div>
						<select
							class="w-full rounded-lg bg-gray-50 dark:bg-gray-850 px-3 py-2 text-sm outline-hidden"
							bind:value={defaultModelId}
						>
							<option value="">{$i18n.t('Not set')}</option>
							{#each $models as model}
								<option value={model.id}>{model.name}</option>
							{/each}
						</select>
					</div>
					<div class="flex gap-2">
						<button
							class="rounded-lg bg-gray-900 dark:bg-white text-white dark:text-gray-900 px-3 py-1.5 text-sm"
							on:click={save}>{$i18n.t('Save')}</button
						>
						{#if isOwner && !isPlatform}
							<button class="rounded-lg text-red-500 px-3 py-1.5 text-sm" on:click={destroy}
								>{$i18n.t('Delete organization')}</button
							>
						{/if}
					</div>
				</div>
			{:else}
				{#if org.description}
					<div class="text-sm text-gray-500">{org.description}</div>
				{/if}
			{/if}

			{#if !isPersonal}
				<div>
					<div class="text-sm font-medium mb-2">{$i18n.t('Members')}</div>
					{#if isAtLeastAdmin}
						<div class="mb-3">
							<input
								class="w-full rounded-lg bg-gray-50 dark:bg-gray-850 px-3 py-2 text-sm outline-hidden"
								placeholder={$i18n.t('Search users to add')}
								bind:value={query}
								on:input={search}
							/>
							{#if results.length}
								<div
									class="mt-1 rounded-lg border border-gray-100 dark:border-gray-850 overflow-hidden"
								>
									{#each results as result}
										<button
											class="w-full text-left px-3 py-2 text-sm hover:bg-gray-50 dark:hover:bg-gray-850"
											on:click={() => add(result.id)}
										>
											{result.name}
											<span class="text-gray-500">· {result.role}</span>
										</button>
									{/each}
								</div>
							{/if}
						</div>
					{/if}

					<div class="flex flex-col gap-2">
						{#each org.members ?? [] as member}
							<div class="flex items-center justify-between rounded-lg px-2 py-1.5">
								<div class="text-sm">
									<div class="font-medium">{member.name ?? member.user_id}</div>
									<div class="text-xs text-gray-500">{member.email ?? ''}</div>
								</div>
								<div class="flex items-center gap-2 text-xs">
									{#if isAtLeastAdmin}
										<select
											class="bg-transparent"
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
										<button class="text-red-500" on:click={() => remove(member.user_id)}
											>{$i18n.t('Remove')}</button
										>
									{:else}
										<span class="text-gray-500 capitalize">{member.role}</span>
									{/if}
								</div>
							</div>
						{/each}
					</div>
				</div>
			{/if}
		</div>
	{/if}
</div>
