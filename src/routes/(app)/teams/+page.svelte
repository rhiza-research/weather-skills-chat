<script lang="ts">
	import { onMount, getContext } from 'svelte';
	import { goto } from '$app/navigation';
	import { toast } from 'svelte-sonner';
	import { teams, WEBUI_NAME, showSidebar } from '$lib/stores';
	import { createTeam, getTeams } from '$lib/apis/teams';
	import MenuLines from '$lib/components/icons/MenuLines.svelte';
	import Plus from '$lib/components/icons/Plus.svelte';

	const i18n = getContext('i18n');

	let name = '';
	let description = '';
	let creating = false;

	const refresh = async () => {
		teams.set(await getTeams(localStorage.token));
	};

	const submit = async () => {
		if (!name.trim()) {
			toast.error($i18n.t('Team name cannot be empty.'));
			return;
		}
		creating = true;
		try {
			const team = await createTeam(localStorage.token, {
				name: name.trim(),
				description: description.trim()
			});
			name = '';
			description = '';
			await refresh();
			goto(`/teams/${team.id}`);
		} catch (error) {
			toast.error(`${error}`);
		}
		creating = false;
	};

	onMount(refresh);
</script>

<svelte:head>
	<title>{$i18n.t('Teams')} | {$WEBUI_NAME}</title>
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
			<div class="text-lg font-medium px-1.5">{$i18n.t('Teams')}</div>
		</div>
	</nav>

	<div class="flex-1 overflow-y-auto px-4 py-4 max-w-3xl w-full mx-auto">
		<form
			class="mb-6 rounded-xl border border-gray-100 dark:border-gray-850 p-4 flex flex-col gap-2"
			on:submit|preventDefault={submit}
		>
			<div class="text-sm font-medium">{$i18n.t('Create a team')}</div>
			<input
				class="w-full rounded-lg bg-gray-50 dark:bg-gray-850 px-3 py-2 text-sm outline-hidden"
				placeholder={$i18n.t('Team name')}
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
			{#each $teams as team}
				<a
					class="rounded-xl border border-gray-100 dark:border-gray-850 px-4 py-3 hover:bg-gray-50 dark:hover:bg-gray-850 transition"
					href="/teams/{team.id}"
				>
					<div class="font-medium">{team.name}</div>
					<div class="text-xs text-gray-500">
						{team.role === 'admin' ? $i18n.t('Admin') : $i18n.t('Member')}
						{#if team.description}
							· {team.description}
						{/if}
					</div>
				</a>
			{:else}
				<div class="text-sm text-gray-500 py-6 text-center">
					{$i18n.t('You are not on any teams yet.')}
				</div>
			{/each}
		</div>
	</div>
</div>
