<script lang="ts">
	import { onMount, getContext } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { teams, WEBUI_NAME, showSidebar } from '$lib/stores';
	import {
		createSecret,
		deleteSecretById,
		getSecrets,
		updateSecretById
	} from '$lib/apis/secrets';
	import MenuLines from '$lib/components/icons/MenuLines.svelte';

	const i18n = getContext('i18n');

	let secrets = [];
	let name = '';
	let value = '';
	let teamId = '';
	let replacing = null;
	let replaceValue = '';

	$: personal = secrets.filter((s) => !s.team_id);
	$: teamNames = new Set(secrets.filter((s) => s.team_id).map((s) => s.name));
	$: byTeam = ($teams ?? []).map((team) => ({
		team,
		items: secrets.filter((s) => s.team_id === team.id)
	}));

	const refresh = async () => {
		secrets = await getSecrets(localStorage.token).catch((error) => {
			toast.error(`${error}`);
			return [];
		});
	};

	const submit = async () => {
		try {
			await createSecret(localStorage.token, {
				name: name.trim(),
				value,
				team_id: teamId || null
			});
			name = '';
			value = '';
			await refresh();
			toast.success($i18n.t('Secret saved'));
		} catch (error) {
			toast.error(`${error}`);
		}
	};

	const replace = async (secret) => {
		if (!replaceValue) {
			toast.error($i18n.t('Enter a new value'));
			return;
		}
		try {
			await updateSecretById(localStorage.token, secret.id, { value: replaceValue });
			replacing = null;
			replaceValue = '';
			await refresh();
			toast.success($i18n.t('Secret updated'));
		} catch (error) {
			toast.error(`${error}`);
		}
	};

	const remove = async (secret) => {
		if (!confirm($i18n.t('Delete this secret? The value cannot be recovered.'))) return;
		try {
			await deleteSecretById(localStorage.token, secret.id);
			await refresh();
		} catch (error) {
			toast.error(`${error}`);
		}
	};

	onMount(refresh);
</script>

<svelte:head>
	<title>{$i18n.t('Secrets')} | {$WEBUI_NAME}</title>
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
			<div class="text-lg font-medium px-1.5">{$i18n.t('Secrets')}</div>
		</div>
	</nav>

	<div class="flex-1 overflow-y-auto px-4 py-4 max-w-3xl w-full mx-auto flex flex-col gap-4">
		<p class="text-xs text-gray-500">
			{$i18n.t(
				'Values are encrypted at rest and never shown again. In a tool call, use a secret placeholder — the server fills the value in before the tool runs. A personal secret overrides a team secret with the same name.'
			)}
			<span class="font-mono">&#123;&#123;secret:NAME&#125;&#125;</span>
		</p>

		<form
			class="rounded-xl border border-gray-100 dark:border-gray-850 p-4 flex flex-col gap-2"
			on:submit|preventDefault={submit}
		>
			<div class="text-sm font-medium">{$i18n.t('Add a secret')}</div>
			<input
				class="rounded-lg bg-gray-50 dark:bg-gray-850 px-3 py-2 text-sm outline-hidden"
				placeholder={$i18n.t('Name (e.g. ECMWF_API_KEY)')}
				bind:value={name}
				autocomplete="off"
				required
			/>
			<input
				class="rounded-lg bg-gray-50 dark:bg-gray-850 px-3 py-2 text-sm outline-hidden"
				type="password"
				placeholder={$i18n.t('Value')}
				bind:value
				autocomplete="new-password"
				required
			/>
			<select class="rounded-lg bg-gray-50 dark:bg-gray-850 px-3 py-2 text-sm" bind:value={teamId}>
				<option value="">{$i18n.t('Personal')}</option>
				{#each ($teams ?? []).filter((t) => t.role === 'admin') as team}
					<option value={team.id}>{team.name}</option>
				{/each}
			</select>
			<button
				class="self-start rounded-lg bg-gray-900 dark:bg-white text-white dark:text-gray-900 px-3 py-1.5 text-sm"
				type="submit">{$i18n.t('Save secret')}</button
			>
		</form>

		<section class="flex flex-col gap-2">
			<div class="text-xs font-medium text-gray-500 uppercase tracking-wide">
				{$i18n.t('Personal')}
			</div>
			{#each personal as secret}
				<div class="rounded-xl border border-gray-100 dark:border-gray-850 p-3">
					<div class="flex items-start justify-between gap-3">
						<div>
							<div class="font-medium text-sm">{secret.name}</div>
							<div class="text-xs text-gray-400 font-mono">{'{{secret:' + secret.name + '}}'}</div>
							{#if teamNames.has(secret.name)}
								<div class="text-[11px] text-gray-500 mt-1">
									{$i18n.t('Overrides the team secret with this name')}
								</div>
							{/if}
						</div>
						<div class="flex gap-2 text-xs shrink-0">
							<button class="text-gray-500" on:click={() => (replacing = secret.id)}
								>{$i18n.t('Replace')}</button
							>
							<button class="text-red-500" on:click={() => remove(secret)}>{$i18n.t('Delete')}</button>
						</div>
					</div>
					{#if replacing === secret.id}
						<form class="mt-2 flex gap-2" on:submit|preventDefault={() => replace(secret)}>
							<input
								class="flex-1 rounded-lg bg-gray-50 dark:bg-gray-850 px-3 py-1.5 text-sm"
								type="password"
								placeholder={$i18n.t('New value')}
								bind:value={replaceValue}
								autocomplete="new-password"
							/>
							<button class="text-xs" type="submit">{$i18n.t('Save')}</button>
							<button class="text-xs text-gray-400" type="button" on:click={() => (replacing = null)}
								>{$i18n.t('Cancel')}</button
							>
						</form>
					{/if}
				</div>
			{:else}
				<div class="text-xs text-gray-400">{$i18n.t('No personal secrets yet.')}</div>
			{/each}
		</section>

		{#each byTeam as group}
			<section class="flex flex-col gap-2">
				<div class="text-xs font-medium text-gray-500 uppercase tracking-wide">
					{group.team.name}
				</div>
				{#each group.items as secret}
					<div class="rounded-xl border border-gray-100 dark:border-gray-850 p-3">
						<div class="flex items-start justify-between gap-3">
							<div>
								<div class="font-medium text-sm">{secret.name}</div>
								<div class="text-xs text-gray-400 font-mono">{'{{secret:' + secret.name + '}}'}</div>
								{#if secret.overridden}
									<div class="text-[11px] text-amber-600 dark:text-amber-400 mt-1">
										{$i18n.t('Overridden by your personal secret with this name')}
									</div>
								{/if}
							</div>
							{#if secret.can_manage}
								<div class="flex gap-2 text-xs shrink-0">
									<button class="text-gray-500" on:click={() => (replacing = secret.id)}
										>{$i18n.t('Replace')}</button
									>
									<button class="text-red-500" on:click={() => remove(secret)}
										>{$i18n.t('Delete')}</button
									>
								</div>
							{/if}
						</div>
						{#if replacing === secret.id}
							<form class="mt-2 flex gap-2" on:submit|preventDefault={() => replace(secret)}>
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
			</section>
		{/each}
	</div>
</div>
