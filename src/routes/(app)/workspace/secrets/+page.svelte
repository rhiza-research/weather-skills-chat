<script lang="ts">
	import { onMount, getContext, tick } from 'svelte';
	import { page } from '$app/stores';
	import { toast } from 'svelte-sonner';
	import { organizations, activeOrganizationId, WEBUI_NAME, user } from '$lib/stores';
	import {
		createSecret,
		deleteSecretById,
		getSecrets,
		updateSecretById
	} from '$lib/apis/secrets';

	import Badge from '$lib/components/common/Badge.svelte';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import Plus from '$lib/components/icons/Plus.svelte';
	import Search from '$lib/components/icons/Search.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';

	const i18n = getContext('i18n');

	let loaded = false;
	let secrets = [];
	let query = '';
	let showAdd = false;
	let name = '';
	let value = '';
	let visibility = 'private';
	let replacing = null;
	let replaceValue = '';
	let selectedSecret = null;
	let showDeleteConfirm = false;
	let nameInput;
	let valueInput;

	const secretNameFromQuery = (raw) => {
		const cleaned = (raw || '').trim();
		return /^[A-Za-z_][A-Za-z0-9_]{0,127}$/.test(cleaned) ? cleaned : '';
	};

	$: currentOrg = ($organizations ?? []).find((org) => org.id === $activeOrganizationId);
	$: isPersonal =
		!currentOrg || currentOrg.kind === 'personal' || $activeOrganizationId === $user?.id;
	$: isOrgAdmin = currentOrg?.role === 'owner' || currentOrg?.role === 'admin';
	$: sharedNames = new Set(
		secrets.filter((s) => s.visibility === 'organization').map((s) => s.name)
	);

	$: items = secrets.filter((secret) => {
		if (isPersonal && secret.visibility === 'organization') return false;
		if (!query.trim()) return true;
		return secret.name.toLowerCase().includes(query.trim().toLowerCase());
	});

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
				visibility: isPersonal ? 'private' : visibility
			});
			name = '';
			value = '';
			visibility = 'private';
			showAdd = false;
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

	const remove = async () => {
		if (!selectedSecret) return;
		try {
			await deleteSecretById(localStorage.token, selectedSecret.id);
			selectedSecret = null;
			await refresh();
		} catch (error) {
			toast.error(`${error}`);
		}
	};

	const openAdd = async () => {
		showAdd = !showAdd;
		if (showAdd) {
			await tick();
			nameInput?.focus();
		}
	};

	onMount(async () => {
		await refresh();
		const prefilled = secretNameFromQuery($page.url.searchParams.get('name'));
		if (prefilled) {
			name = prefilled;
			showAdd = true;
		}
		loaded = true;
		if (prefilled) {
			await tick();
			valueInput?.focus();
		}
	});
</script>

<svelte:head>
	<title>{$i18n.t('Secrets')} | {$WEBUI_NAME}</title>
</svelte:head>

<ConfirmDialog
	bind:show={showDeleteConfirm}
	title={$i18n.t('Delete')}
	message={$i18n.t('Delete this secret? The value cannot be recovered.')}
	onConfirm={remove}
/>

{#if loaded}
	<div class="flex flex-col gap-1 my-1.5">
		<div class="flex justify-between items-center">
			<div class="flex md:self-center text-xl font-medium px-0.5 items-center">
				{$i18n.t('Secrets')}
				<div class="flex self-center w-[1px] h-6 mx-2.5 bg-gray-50 dark:bg-gray-850" />
				<span class="text-lg font-medium text-gray-500 dark:text-gray-300">{items.length}</span>
			</div>
		</div>

		<div class="flex w-full space-x-2">
			<div class="flex flex-1">
				<div class="self-center ml-1 mr-3">
					<Search className="size-3.5" />
				</div>
				<input
					class="w-full text-sm py-1 rounded-r-xl outline-hidden bg-transparent"
					bind:value={query}
					placeholder={$i18n.t('Search Secrets')}
				/>
			</div>
			<div>
				<button
					class="px-2 py-2 rounded-xl hover:bg-gray-700/10 dark:hover:bg-gray-100/10 dark:text-gray-300 dark:hover:text-white transition font-medium text-sm flex items-center space-x-1"
					aria-label={$i18n.t('Add a secret')}
					on:click={openAdd}
				>
					<Plus className="size-3.5" />
				</button>
			</div>
		</div>
	</div>

	{#if showAdd}
		<form
			class="flex flex-col md:flex-row gap-2 mb-4 mt-2 p-3 rounded-xl bg-gray-50 dark:bg-gray-850 border border-gray-100 dark:border-gray-800"
			on:submit|preventDefault={submit}
		>
			<input
				bind:this={nameInput}
				class="flex-1 w-full text-sm rounded-lg py-2 px-3 bg-transparent outline-hidden"
				placeholder={$i18n.t('Name (e.g. ECMWF_API_KEY)')}
				bind:value={name}
				autocomplete="off"
				required
			/>
			<input
				bind:this={valueInput}
				class="flex-1 w-full text-sm rounded-lg py-2 px-3 bg-transparent outline-hidden border border-gray-200 dark:border-gray-700"
				type="password"
				placeholder={$i18n.t('Value')}
				bind:value
				autocomplete="new-password"
				required
			/>
			{#if !isPersonal && isOrgAdmin}
				<select
					class="md:w-40 w-full text-sm rounded-lg py-2 px-3 bg-transparent outline-hidden border border-gray-200 dark:border-gray-700"
					bind:value={visibility}
				>
					<option value="private">{$i18n.t('Private')}</option>
					<option value="organization">{$i18n.t('Organization')}</option>
				</select>
			{/if}
			<button
				class="px-3.5 py-2 text-sm rounded-lg bg-gray-900 text-white dark:bg-white dark:text-gray-900"
				type="submit"
			>
				{$i18n.t('Save')}
			</button>
		</form>
	{/if}

	<div class="my-2 mb-5 gap-2 grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3">
		{#each items as secret (secret.id)}
			<div
				class="flex space-x-4 cursor-default text-left w-full px-3 py-2 hover:bg-gray-50 dark:hover:bg-gray-850 transition rounded-xl"
			>
				<div class="w-full">
					<div class="flex items-center justify-between -mt-1">
						{#if secret.visibility === 'organization'}
							<Badge type="success" content={$i18n.t('Organization')} />
						{:else}
							<Badge type="muted" content={$i18n.t('Private')} />
						{/if}

						{#if secret.visibility !== 'organization' || secret.can_manage}
							<div class="flex self-center gap-0.5 -mr-1 translate-y-1">
								<button
									class="text-xs px-2 py-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800"
									on:click={() => {
										replacing = replacing === secret.id ? null : secret.id;
										replaceValue = '';
									}}
								>
									{$i18n.t('Replace')}
								</button>
								<button
									class="text-xs px-2 py-1.5 rounded-lg text-red-600 hover:bg-red-50 dark:hover:bg-red-950"
									on:click={() => {
										selectedSecret = secret;
										showDeleteConfirm = true;
									}}
								>
									{$i18n.t('Delete')}
								</button>
							</div>
						{/if}
					</div>

					<div class="px-1 mb-1">
						<div class="font-semibold line-clamp-1 h-fit">{secret.name}</div>
						<div class="text-xs overflow-hidden text-ellipsis line-clamp-1 font-mono text-gray-500">
							{'{{secret:' + secret.name + '}}'}
						</div>

					{#if secret.visibility !== 'organization' && sharedNames.has(secret.name)}
						<div class="mt-2 text-xs text-gray-500">
							{$i18n.t('Overrides the organization secret with this name')}
						</div>
					{/if}
					{#if secret.overridden}
						<div class="mt-2 text-xs text-amber-600 dark:text-amber-400">
							{$i18n.t('Overridden by your personal secret with this name')}
						</div>
					{/if}

					{#if replacing === secret.id}
						<form class="mt-3 flex gap-2" on:submit|preventDefault={() => replace(secret)}>
							<input
								class="flex-1 w-full text-sm rounded-lg py-1.5 px-2.5 bg-gray-50 dark:bg-gray-850 outline-hidden"
								type="password"
								placeholder={$i18n.t('New value')}
								bind:value={replaceValue}
								autocomplete="new-password"
							/>
							<button class="text-xs px-2 py-1.5 rounded-lg" type="submit">{$i18n.t('Save')}</button>
							<button
								class="text-xs px-2 py-1.5 rounded-lg text-gray-500"
								type="button"
								on:click={() => {
									replacing = null;
									replaceValue = '';
								}}>{$i18n.t('Cancel')}</button
							>
						</form>
					{/if}
					</div>
				</div>
			</div>
		{:else}
			<div class="col-span-full text-sm text-gray-500 dark:text-gray-400 py-6 text-center">
				{$i18n.t('No secrets yet.')}
			</div>
		{/each}
	</div>

	<div class="text-gray-500 text-xs mt-1 mb-2">
		ⓘ {$i18n.t(
			'Values are encrypted at rest and never shown again. In a tool call, use a secret placeholder — the server fills the value in before the tool runs. A private secret overrides an organization secret with the same name.'
		)}
		<span class="font-mono">&#123;&#123;secret:NAME&#125;&#125;</span>
	</div>
{:else}
	<div class="w-full h-full flex justify-center items-center">
		<Spinner />
	</div>
{/if}
