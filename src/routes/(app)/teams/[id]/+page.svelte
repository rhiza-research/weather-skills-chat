<script lang="ts">
	import { onMount, getContext } from 'svelte';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { toast } from 'svelte-sonner';
	import { models, teams, user, WEBUI_NAME, showSidebar } from '$lib/stores';
	import {
		addTeamMember,
		deleteTeamById,
		getTeamById,
		getTeams,
		removeTeamMember,
		updateTeamById,
		updateTeamMemberRole
	} from '$lib/apis/teams';
	import { searchUsers } from '$lib/apis/users';
	import {
		createSecret,
		deleteSecretById,
		getTeamSecrets,
		updateSecretById
	} from '$lib/apis/secrets';
	import MenuLines from '$lib/components/icons/MenuLines.svelte';

	const i18n = getContext('i18n');

	let team = null;
	let query = '';
	let results = [];
	let name = '';
	let description = '';
	let defaultModelId = '';
	let secrets = [];
	let secretName = '';
	let secretValue = '';
	let replacing = null;
	let replaceValue = '';

	$: id = $page.params.id;
	$: isAdmin = team?.role === 'admin' || $user?.role === 'admin';

	const load = async () => {
		try {
			team = await getTeamById(localStorage.token, id);
			name = team.name;
			description = team.description ?? '';
			defaultModelId = (team.default_models || '').split(',')[0]?.trim() ?? '';
			secrets = await getTeamSecrets(localStorage.token, id).catch(() => []);
		} catch (error) {
			toast.error(`${error}`);
			goto('/teams');
		}
	};

	const addSecret = async () => {
		try {
			await createSecret(localStorage.token, {
				name: secretName.trim(),
				value: secretValue,
				team_id: id
			});
			secretName = '';
			secretValue = '';
			secrets = await getTeamSecrets(localStorage.token, id);
			toast.success($i18n.t('Secret saved'));
		} catch (error) {
			toast.error(`${error}`);
		}
	};

	const replaceSecret = async (secret) => {
		if (!replaceValue) {
			toast.error($i18n.t('Enter a new value'));
			return;
		}
		try {
			await updateSecretById(localStorage.token, secret.id, { value: replaceValue });
			replacing = null;
			replaceValue = '';
			secrets = await getTeamSecrets(localStorage.token, id);
			toast.success($i18n.t('Secret updated'));
		} catch (error) {
			toast.error(`${error}`);
		}
	};

	const removeSecret = async (secret) => {
		if (!confirm($i18n.t('Delete this secret? The value cannot be recovered.'))) return;
		try {
			await deleteSecretById(localStorage.token, secret.id);
			secrets = await getTeamSecrets(localStorage.token, id);
		} catch (error) {
			toast.error(`${error}`);
		}
	};

	const save = async () => {
		try {
			team = await updateTeamById(localStorage.token, id, {
				name,
				description,
				default_models: defaultModelId || ''
			});
			teams.set(await getTeams(localStorage.token));
			toast.success($i18n.t('Team updated'));
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
			team = await addTeamMember(localStorage.token, id, userId, 'member');
			query = '';
			results = [];
			teams.set(await getTeams(localStorage.token));
		} catch (error) {
			toast.error(`${error}`);
		}
	};

	const changeRole = async (userId: string, role: string) => {
		try {
			team = await updateTeamMemberRole(localStorage.token, id, userId, role);
		} catch (error) {
			toast.error(`${error}`);
		}
	};

	const remove = async (userId: string) => {
		try {
			team = await removeTeamMember(localStorage.token, id, userId);
			if (userId === $user?.id) {
				teams.set(await getTeams(localStorage.token));
				goto('/teams');
			}
		} catch (error) {
			toast.error(`${error}`);
		}
	};

	const destroy = async () => {
		if (
			!confirm(
				$i18n.t(
					'Delete this team? All team chats (including archived) must be deleted first.'
				)
			)
		)
			return;
		try {
			await deleteTeamById(localStorage.token, id);
			teams.set(await getTeams(localStorage.token));
			goto('/teams');
		} catch (error) {
			toast.error(`${error}`);
		}
	};

	onMount(load);
	$: if (id) load();
</script>

<svelte:head>
	<title>{team?.name ?? $i18n.t('Team')} | {$WEBUI_NAME}</title>
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
			<a class="text-sm text-gray-500 px-1.5" href="/teams">{$i18n.t('Teams')}</a>
			<div class="text-lg font-medium">{team?.name ?? ''}</div>
		</div>
	</nav>

	{#if team}
		<div class="flex-1 overflow-y-auto px-4 py-4 max-w-3xl w-full mx-auto flex flex-col gap-6">
			{#if isAdmin}
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
						<p class="text-xs text-gray-400 mt-1">
							{$i18n.t('Used for new team chats. Members can still switch models.')}
						</p>
					</div>
					<div class="flex gap-2">
						<button
							class="rounded-lg bg-gray-900 dark:bg-white text-white dark:text-gray-900 px-3 py-1.5 text-sm"
							on:click={save}>{$i18n.t('Save')}</button
						>
						<button
							class="rounded-lg text-red-500 px-3 py-1.5 text-sm"
							on:click={destroy}>{$i18n.t('Delete team')}</button
						>
					</div>
				</div>
			{:else}
				{#if team.description}
					<div class="text-sm text-gray-500">{team.description}</div>
				{/if}
				{#if defaultModelId}
					<div class="text-sm text-gray-500">
						{$i18n.t('Default Model')}:
						{$models.find((m) => m.id === defaultModelId)?.name ?? defaultModelId}
					</div>
				{/if}
			{/if}

			<div>
				<div class="text-sm font-medium mb-2">{$i18n.t('Secrets')}</div>
				<p class="text-xs text-gray-500 mb-2">
					{$i18n.t('Values are never shown after save. Use')}
					<span class="font-mono">&#123;&#123;secret:NAME&#125;&#125;</span>
					{$i18n.t('in tool calls.')}
				</p>
				{#if isAdmin}
					<form class="mb-3 flex flex-col gap-2" on:submit|preventDefault={addSecret}>
						<input
							class="w-full rounded-lg bg-gray-50 dark:bg-gray-850 px-3 py-2 text-sm outline-hidden"
							placeholder={$i18n.t('Name (e.g. ECMWF_API_KEY)')}
							bind:value={secretName}
							autocomplete="off"
							required
						/>
						<input
							class="w-full rounded-lg bg-gray-50 dark:bg-gray-850 px-3 py-2 text-sm outline-hidden"
							type="password"
							placeholder={$i18n.t('Value')}
							bind:value={secretValue}
							autocomplete="new-password"
							required
						/>
						<button
							class="self-start rounded-lg bg-gray-900 dark:bg-white text-white dark:text-gray-900 px-3 py-1.5 text-sm"
							type="submit">{$i18n.t('Save secret')}</button
						>
					</form>
				{/if}
				<div class="flex flex-col gap-2 mb-6">
					{#each secrets as secret}
						<div class="rounded-lg border border-gray-100 dark:border-gray-850 p-3">
							<div class="flex items-start justify-between gap-3">
								<div>
									<div class="text-sm font-medium">{secret.name}</div>
									<div class="text-xs text-gray-400 font-mono">
										{'{{secret:' + secret.name + '}}'}
									</div>
									{#if secret.overridden}
										<div class="text-[11px] text-amber-600 dark:text-amber-400 mt-1">
											{$i18n.t('Overridden by your personal secret with this name')}
										</div>
									{/if}
								</div>
								{#if isAdmin}
									<div class="flex gap-2 text-xs">
										<button class="text-gray-500" on:click={() => (replacing = secret.id)}
											>{$i18n.t('Replace')}</button
										>
										<button class="text-red-500" on:click={() => removeSecret(secret)}
											>{$i18n.t('Delete')}</button
										>
									</div>
								{/if}
							</div>
							{#if replacing === secret.id}
								<form class="mt-2 flex gap-2" on:submit|preventDefault={() => replaceSecret(secret)}>
									<input
										class="flex-1 rounded-lg bg-gray-50 dark:bg-gray-850 px-3 py-1.5 text-sm"
										type="password"
										placeholder={$i18n.t('New value')}
										bind:value={replaceValue}
										autocomplete="new-password"
									/>
									<button class="text-xs" type="submit">{$i18n.t('Save')}</button>
									<button
										class="text-xs text-gray-400"
										type="button"
										on:click={() => (replacing = null)}>{$i18n.t('Cancel')}</button
									>
								</form>
							{/if}
						</div>
					{:else}
						<div class="text-xs text-gray-400">{$i18n.t('No team secrets yet.')}</div>
					{/each}
				</div>
			</div>

			<div>
				<div class="text-sm font-medium mb-2">{$i18n.t('Members')}</div>
				{#if isAdmin}
					<div class="mb-3">
						<input
							class="w-full rounded-lg bg-gray-50 dark:bg-gray-850 px-3 py-2 text-sm outline-hidden"
							placeholder={$i18n.t('Search users to add')}
							bind:value={query}
							on:input={search}
						/>
						{#if results.length}
							<div class="mt-1 rounded-lg border border-gray-100 dark:border-gray-850 overflow-hidden">
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
					{#each team.members ?? [] as member}
						<div class="flex items-center justify-between rounded-lg px-2 py-1.5">
							<div class="text-sm">
								<div class="font-medium">{member.name ?? member.user_id}</div>
								<div class="text-xs text-gray-500">{member.email ?? ''}</div>
							</div>
							<div class="flex items-center gap-2 text-xs">
								{#if isAdmin}
									<select
										class="bg-transparent"
										value={member.role}
										on:change={(e) => changeRole(member.user_id, e.currentTarget.value)}
									>
										<option value="member">{$i18n.t('Member')}</option>
										<option value="admin">{$i18n.t('Admin')}</option>
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
		</div>
	{/if}
</div>
