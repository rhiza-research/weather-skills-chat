<script lang="ts">
	import { onMount, getContext } from 'svelte';
	import { goto } from '$app/navigation';
	import { toast } from 'svelte-sonner';
	import { organizations, user, WEBUI_NAME, showSidebar } from '$lib/stores';
	import { createOrganization, getAllOrganizations, getOrganizations } from '$lib/apis/organizations';
	import MenuLines from '$lib/components/icons/MenuLines.svelte';
	import Plus from '$lib/components/icons/Plus.svelte';

	const i18n = getContext('i18n');

	let name = '';
	let description = '';
	let creating = false;
	let allOrgs = [];

	$: memberships = ($organizations ?? []).filter((org) => org.kind !== 'personal');
	$: isPlatformAdmin = $user?.role === 'admin';

	const refresh = async () => {
		organizations.set(await getOrganizations(localStorage.token));
		if (isPlatformAdmin) {
			allOrgs = await getAllOrganizations(localStorage.token).catch(() => []);
		}
	};

	const submit = async () => {
		if (!name.trim()) {
			toast.error($i18n.t('Organization name cannot be empty.'));
			return;
		}
		creating = true;
		try {
			const org = await createOrganization(localStorage.token, {
				name: name.trim(),
				description: description.trim()
			});
			name = '';
			description = '';
			await refresh();
			goto(`/organizations/${org.id}`);
		} catch (error) {
			toast.error(`${error}`);
		}
		creating = false;
	};

	onMount(refresh);
</script>

<svelte:head>
	<title>{$i18n.t('Organizations')} | {$WEBUI_NAME}</title>
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
			<div class="text-lg font-medium px-1.5">{$i18n.t('Organizations')}</div>
		</div>
	</nav>

	<div class="flex-1 overflow-y-auto px-4 py-4 max-w-3xl w-full mx-auto">
		<form
			class="mb-6 rounded-xl border border-gray-100 dark:border-gray-850 p-4 flex flex-col gap-2"
			on:submit|preventDefault={submit}
		>
			<div class="text-sm font-medium">{$i18n.t('Create an organization')}</div>
			<input
				class="w-full rounded-lg bg-gray-50 dark:bg-gray-850 px-3 py-2 text-sm outline-hidden"
				placeholder={$i18n.t('Organization name')}
				bind:value={name}
			/>
			<textarea
				class="w-full rounded-lg bg-gray-50 dark:bg-gray-850 px-3 py-2 text-sm outline-hidden"
				placeholder={$i18n.t('Description')}
				rows="2"
				bind:value={description}
			/>
			<button
				class="self-start flex items-center gap-1 rounded-lg bg-gray-900 dark:bg-white text-white dark:text-gray-900 px-3 py-1.5 text-sm"
				disabled={creating}
				type="submit"
			>
				<Plus className="size-4" />
				{$i18n.t('Create')}
			</button>
		</form>

		<div class="flex flex-col gap-2">
			{#each memberships as org}
				<a
					class="rounded-xl border border-gray-100 dark:border-gray-850 px-4 py-3 hover:bg-gray-50 dark:hover:bg-gray-850 transition"
					href="/organizations/{org.id}"
				>
					<div class="font-medium">{org.name}</div>
					<div class="text-xs text-gray-500">
						{org.role === 'owner'
							? $i18n.t('Owner')
							: org.role === 'admin'
								? $i18n.t('Admin')
								: $i18n.t('User')}
						{#if org.description}
							· {org.description}
						{/if}
					</div>
				</a>
			{:else}
				<div class="text-sm text-gray-500 py-6 text-center">
					{$i18n.t('You are not in any workspace organizations yet.')}
				</div>
			{/each}
		</div>

		{#if isPlatformAdmin && allOrgs.length}
			<div class="mt-8 text-sm font-medium mb-2">{$i18n.t('All organizations')}</div>
			<div class="flex flex-col gap-2">
				{#each allOrgs.filter((org) => org.kind !== 'personal') as org}
					<a
						class="rounded-xl border border-gray-100 dark:border-gray-850 px-4 py-3 hover:bg-gray-50 dark:hover:bg-gray-850 transition"
						href="/organizations/{org.id}"
					>
						<div class="font-medium">{org.name}</div>
						<div class="text-xs text-gray-500 capitalize">{org.kind}</div>
					</a>
				{/each}
			</div>
		{/if}
	</div>
</div>
