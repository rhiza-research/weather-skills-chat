<script lang="ts">
	import { onMount, getContext } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { organizations, activeOrganizationId, WEBUI_NAME, user } from '$lib/stores';
	import {
		createPreference,
		deletePreferenceById,
		getPreferences,
		updatePreferenceById
	} from '$lib/apis/preferences';

	import Badge from '$lib/components/common/Badge.svelte';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import Plus from '$lib/components/icons/Plus.svelte';
	import Search from '$lib/components/icons/Search.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import Switch from '$lib/components/common/Switch.svelte';

	const i18n = getContext('i18n');

	let loaded = false;
	let preferences = [];
	let query = '';
	let showAdd = false;
	let title = '';
	let content = '';
	let visibility = 'private';
	let editing = null;
	let editTitle = '';
	let editContent = '';
	let selectedPreference = null;
	let showDeleteConfirm = false;

	$: currentOrg = ($organizations ?? []).find((org) => org.id === $activeOrganizationId);
	$: isPersonal =
		!currentOrg || currentOrg.kind === 'personal' || $activeOrganizationId === $user?.id;
	$: isOrgAdmin = currentOrg?.role === 'owner' || currentOrg?.role === 'admin';

	$: items = preferences.filter((preference) => {
		if (isPersonal && preference.visibility === 'organization') return false;
		if (!query.trim()) return true;
		const haystack = `${preference.title}\n${preference.content}`.toLowerCase();
		return haystack.includes(query.trim().toLowerCase());
	});

	const refresh = async () => {
		preferences = await getPreferences(localStorage.token).catch((error) => {
			toast.error(`${error}`);
			return [];
		});
	};

	const submit = async () => {
		try {
			await createPreference(localStorage.token, {
				title: title.trim(),
				content,
				visibility: isPersonal ? 'private' : visibility
			});
			title = '';
			content = '';
			visibility = 'private';
			showAdd = false;
			await refresh();
			toast.success($i18n.t('Preference saved'));
		} catch (error) {
			toast.error(`${error}`);
		}
	};

	const saveEdit = async (preference) => {
		try {
			await updatePreferenceById(localStorage.token, preference.id, {
				title: editTitle.trim(),
				content: editContent
			});
			editing = null;
			await refresh();
			toast.success($i18n.t('Preference updated'));
		} catch (error) {
			toast.error(`${error}`);
		}
	};

	const setEnabled = async (preference, enabled) => {
		if (!preference.can_manage || enabled === preference.enabled) return;
		const previous = preference.enabled;
		preference.enabled = enabled;
		preferences = preferences;
		try {
			await updatePreferenceById(localStorage.token, preference.id, { enabled });
			await refresh();
		} catch (error) {
			preference.enabled = previous;
			preferences = preferences;
			toast.error(`${error}`);
		}
	};

	const remove = async () => {
		if (!selectedPreference) return;
		try {
			await deletePreferenceById(localStorage.token, selectedPreference.id);
			selectedPreference = null;
			await refresh();
		} catch (error) {
			toast.error(`${error}`);
		}
	};

	onMount(async () => {
		await refresh();
		loaded = true;
	});
</script>

<svelte:head>
	<title>{$i18n.t('Preferences')} | {$WEBUI_NAME}</title>
</svelte:head>

<ConfirmDialog
	bind:show={showDeleteConfirm}
	title={$i18n.t('Delete')}
	message={$i18n.t('Delete this preference?')}
	onConfirm={remove}
/>

{#if loaded}
	<div class="flex flex-col gap-1 my-1.5">
		<div class="flex justify-between items-center">
			<div class="flex md:self-center text-xl font-medium px-0.5 items-center">
				{$i18n.t('Preferences')}
				<div class="flex self-center w-[1px] h-6 mx-2.5 bg-gray-50 dark:bg-gray-850" />
				<span class="text-lg font-medium text-gray-500 dark:text-gray-300">{items.length}</span>
			</div>
		</div>
		<div class="text-sm text-gray-500 dark:text-gray-400 mb-2">
			{$i18n.t(
				'Enabled preferences are added to your chats. Organization preferences apply to every member.'
			)}
		</div>

		<div class="flex w-full space-x-2">
			<div class="flex flex-1">
				<div class="self-center ml-1 mr-3">
					<Search className="size-3.5" />
				</div>
				<input
					class="w-full text-sm py-1 rounded-r-xl outline-hidden bg-transparent"
					bind:value={query}
					placeholder={$i18n.t('Search Preferences')}
				/>
			</div>
			<div>
				<button
					class="px-2 py-2 rounded-xl hover:bg-gray-700/10 dark:hover:bg-gray-100/10 dark:text-gray-300 dark:hover:text-white transition font-medium text-sm flex items-center space-x-1"
					aria-label={$i18n.t('Add a preference')}
					on:click={() => (showAdd = !showAdd)}
				>
					<Plus className="size-3.5" />
				</button>
			</div>
		</div>
	</div>

	{#if showAdd}
		<form
			class="flex flex-col gap-2 mb-4 mt-2 p-3 rounded-xl bg-gray-50 dark:bg-gray-850 border border-gray-100 dark:border-gray-800"
			on:submit|preventDefault={submit}
		>
			<input
				class="w-full text-sm rounded-lg py-2 px-3 bg-transparent outline-hidden"
				placeholder={$i18n.t('Title')}
				bind:value={title}
				required
			/>
			<textarea
				class="w-full min-h-28 text-sm rounded-lg py-2 px-3 bg-transparent outline-hidden border border-gray-200 dark:border-gray-700"
				placeholder={$i18n.t('Preference text')}
				bind:value={content}
				required
			></textarea>
			<div class="flex flex-col md:flex-row gap-2 md:items-center md:justify-between">
				{#if !isPersonal && isOrgAdmin}
					<select
						class="md:w-40 w-full text-sm rounded-lg py-2 px-3 bg-transparent outline-hidden border border-gray-200 dark:border-gray-700"
						bind:value={visibility}
					>
						<option value="private">{$i18n.t('Private')}</option>
						<option value="organization">{$i18n.t('Organization')}</option>
					</select>
				{:else}
					<div></div>
				{/if}
				<button
					class="px-3.5 py-2 text-sm rounded-lg bg-gray-900 text-white dark:bg-white dark:text-gray-900"
					type="submit"
				>
					{$i18n.t('Save')}
				</button>
			</div>
		</form>
	{/if}

	<div class="my-2 mb-5 flex flex-col gap-2">
		{#each items as preference (preference.id)}
			<div class="px-3 py-3 rounded-xl border border-gray-100 dark:border-gray-800">
				<div class="flex items-start justify-between gap-3">
					<div class="min-w-0">
						<div class="flex items-center gap-2">
							{#if preference.visibility === 'organization'}
								<Badge type="success" content={$i18n.t('Organization')} />
							{:else}
								<Badge type="muted" content={$i18n.t('Private')} />
							{/if}
							<div class="font-semibold truncate">{preference.title}</div>
						</div>
					</div>
					<div class="flex items-center gap-2 shrink-0">
						{#if preference.can_manage}
							<Switch
								state={!!preference.enabled}
								on:change={(e) => setEnabled(preference, !!e.detail)}
							/>
						{:else}
							<span class="text-xs text-gray-500">
								{preference.enabled ? $i18n.t('Enabled') : $i18n.t('Disabled')}
							</span>
						{/if}
					</div>
				</div>

				{#if editing === preference.id}
					<div class="mt-3 flex flex-col gap-2">
						<input
							class="w-full text-sm rounded-lg py-2 px-3 bg-transparent outline-hidden border border-gray-200 dark:border-gray-700"
							bind:value={editTitle}
						/>
						<textarea
							class="w-full min-h-28 text-sm rounded-lg py-2 px-3 bg-transparent outline-hidden border border-gray-200 dark:border-gray-700"
							bind:value={editContent}
						></textarea>
						<div class="flex gap-2">
							<button
								class="text-xs px-2 py-1.5 rounded-lg bg-gray-900 text-white dark:bg-white dark:text-gray-900"
								on:click={() => saveEdit(preference)}
							>
								{$i18n.t('Save')}
							</button>
							<button
								class="text-xs px-2 py-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800"
								on:click={() => (editing = null)}
							>
								{$i18n.t('Cancel')}
							</button>
						</div>
					</div>
				{:else}
					<div class="mt-2 text-sm text-gray-600 dark:text-gray-300 whitespace-pre-wrap">
						{preference.content}
					</div>
					{#if preference.can_manage}
						<div class="mt-2 flex gap-1">
							<button
								class="text-xs px-2 py-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800"
								on:click={() => {
									editing = preference.id;
									editTitle = preference.title;
									editContent = preference.content;
								}}
							>
								{$i18n.t('Edit')}
							</button>
							<button
								class="text-xs px-2 py-1.5 rounded-lg text-red-600 hover:bg-red-50 dark:hover:bg-red-950"
								on:click={() => {
									selectedPreference = preference;
									showDeleteConfirm = true;
								}}
							>
								{$i18n.t('Delete')}
							</button>
						</div>
					{/if}
				{/if}
			</div>
		{:else}
			<div class="text-sm text-gray-500 dark:text-gray-400 py-6 text-center">
				{$i18n.t('No preferences yet.')}
			</div>
		{/each}
	</div>
{:else}
	<div class="flex justify-center py-8"><Spinner /></div>
{/if}
