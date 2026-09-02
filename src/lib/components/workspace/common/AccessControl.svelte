<script lang="ts">
	import { getContext, onMount } from 'svelte';

	const i18n = getContext('i18n');

	import { getGroups } from '$lib/apis/groups';
	import { getTeams } from '$lib/apis/teams';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Plus from '$lib/components/icons/Plus.svelte';
	import UserCircleSolid from '$lib/components/icons/UserCircleSolid.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';
	import Badge from '$lib/components/common/Badge.svelte';

	export let onChange: Function = () => {};

	export let accessRoles = ['read'];
	export let accessControl = {};

	export let allowPublic = true;

	let selectedGroupId = '';
	let selectedTeamId = '';
	let groups = [];
	let userTeams = [];

	/** Expand private `{}` / partial ACLs so the template can safely read .read/.write. */
	const emptyAclForm = () => ({
		read: {
			group_ids: [],
			team_ids: [],
			user_ids: []
		},
		write: {
			group_ids: [],
			team_ids: [],
			user_ids: []
		}
	});

	const normalizeAclForm = (acl) => {
		if (acl === null) return null;
		return {
			read: {
				group_ids: acl?.read?.group_ids ?? [],
				team_ids: acl?.read?.team_ids ?? [],
				user_ids: acl?.read?.user_ids ?? []
			},
			write: {
				group_ids: acl?.write?.group_ids ?? [],
				team_ids: acl?.write?.team_ids ?? [],
				user_ids: acl?.write?.user_ids ?? []
			}
		};
	};

	// Private packs open as `{}` — normalize before first render or the Groups
	// section throws on accessControl.read and freezes the modal.
	if (accessControl !== null) {
		accessControl = normalizeAclForm(accessControl);
	} else if (!allowPublic) {
		accessControl = emptyAclForm();
	}

	$: if (!allowPublic && accessControl === null) {
		accessControl = emptyAclForm();
		onChange(accessControl);
	}

	onMount(async () => {
		groups = await getGroups(localStorage.token);
		userTeams = await getTeams(localStorage.token).catch(() => []);

		// Re-normalize after mount in case parent rebound a raw `{}` / null.
		// Do not emit onChange here — auto-save callers must not get a spurious write.
		if (accessControl === null) {
			if (!allowPublic) {
				accessControl = emptyAclForm();
				onChange(accessControl);
			}
		} else {
			accessControl = normalizeAclForm(accessControl);
		}
	});

	$: if (selectedGroupId) {
		onSelectGroup();
	}

	$: if (selectedTeamId) {
		onSelectTeam();
	}

	$: accessTeams = userTeams.filter((team) =>
		(accessControl?.read?.team_ids ?? []).includes(team.id)
	);

	const onSelectGroup = () => {
		if (selectedGroupId !== '' && accessControl) {
			accessControl = normalizeAclForm(accessControl);
			accessControl.read.group_ids = [...accessControl.read.group_ids, selectedGroupId];
			selectedGroupId = '';
			onChange(accessControl);
		}
	};

	const onSelectTeam = () => {
		if (selectedTeamId !== '' && accessControl) {
			accessControl = normalizeAclForm(accessControl);
			accessControl.read.team_ids = [...(accessControl.read.team_ids ?? []), selectedTeamId];
			selectedTeamId = '';
			onChange(accessControl);
		}
	};
</script>

<div class=" rounded-lg flex flex-col gap-2">
	<div class="">
		<div class=" text-sm font-semibold mb-1">{$i18n.t('Visibility')}</div>

		<div class="flex gap-2.5 items-center mb-1">
			<div>
				<div class=" p-2 bg-black/5 dark:bg-white/5 rounded-full">
					{#if accessControl !== null}
						<svg
							xmlns="http://www.w3.org/2000/svg"
							fill="none"
							viewBox="0 0 24 24"
							stroke-width="1.5"
							stroke="currentColor"
							class="w-5 h-5"
						>
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								d="M16.5 10.5V6.75a4.5 4.5 0 10-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 002.25-2.25v-6.75a2.25 2.25 0 00-2.25-2.25H6.75a2.25 2.25 0 00-2.25 2.25v6.75a2.25 2.25 0 002.25 2.25z"
							/>
						</svg>
					{:else}
						<svg
							xmlns="http://www.w3.org/2000/svg"
							fill="none"
							viewBox="0 0 24 24"
							stroke-width="1.5"
							stroke="currentColor"
							class="w-5 h-5"
						>
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								d="M6.115 5.19l.319 1.913A6 6 0 008.11 10.36L9.75 12l-.387.775c-.217.433-.132.956.21 1.298l1.348 1.348c.21.21.329.497.329.795v1.089c0 .426.24.815.622 1.006l.153.076c.433.217.956.132 1.298-.21l.723-.723a8.7 8.7 0 002.288-4.042 1.087 1.087 0 00-.358-1.099l-1.33-1.108c-.251-.21-.582-.299-.905-.245l-1.17.195a1.125 1.125 0 01-.98-.314l-.295-.295a1.125 1.125 0 010-1.591l.13-.132a1.125 1.125 0 011.3-.21l.603.302a.809.809 0 001.086-1.086L14.25 7.5l1.256-.837a4.5 4.5 0 001.528-1.732l.146-.292M6.115 5.19A9 9 0 1017.18 4.64M6.115 5.19A8.965 8.965 0 0112 3c1.929 0 3.716.607 5.18 1.64"
							/>
						</svg>
					{/if}
				</div>
			</div>

			<div>
				<select
					id="models"
					class="outline-hidden bg-transparent text-sm font-medium rounded-lg block w-fit pr-10 max-w-full placeholder-gray-400"
					value={accessControl !== null ? 'private' : 'public'}
					on:change={(e) => {
						if (e.target.value === 'public') {
							accessControl = null;
						} else {
							accessControl = {
								read: {
									group_ids: [],
									team_ids: [],
									user_ids: []
								},
								write: {
									group_ids: [],
									team_ids: [],
									user_ids: []
								}
							};
						}
						onChange(accessControl);
					}}
				>
					<option class=" text-gray-700" value="private" selected>{$i18n.t('Private')}</option>
					{#if allowPublic}
						<option class=" text-gray-700" value="public" selected>{$i18n.t('Public')}</option>
					{/if}
				</select>

				<div class=" text-xs text-gray-400 font-medium">
					{#if accessControl !== null}
						{$i18n.t('Only select users and groups with permission can access')}
					{:else}
						{$i18n.t('Accessible to all users')}
					{/if}
				</div>
			</div>
		</div>
	</div>
	{#if accessControl !== null}
		{@const readGroupIds = accessControl?.read?.group_ids ?? []}
		{@const writeGroupIds = accessControl?.write?.group_ids ?? []}
		{@const accessGroups = groups.filter((group) => readGroupIds.includes(group.id))}
		<div>
			<div class="">
				<div class="flex justify-between mb-1.5">
					<div class="text-sm font-semibold">
						{$i18n.t('Groups')}
					</div>
				</div>

				<div class="mb-1">
					<div class="flex w-full">
						<div class="flex flex-1 items-center">
							<div class="w-full px-0.5">
								<select
									class="outline-hidden bg-transparent text-sm rounded-lg block w-full pr-10 max-w-full
									{selectedGroupId ? '' : 'text-gray-500'}
									dark:placeholder-gray-500"
									bind:value={selectedGroupId}
								>
									<option class=" text-gray-700" value="" disabled selected
										>{$i18n.t('Select a group')}</option
									>
									{#each groups.filter((group) => !readGroupIds.includes(group.id)) as group}
										<option class=" text-gray-700" value={group.id}>{group.name}</option>
									{/each}
								</select>
							</div>
							<!-- <div>
								<Tooltip content={$i18n.t('Add Group')}>
									<button
										class=" p-1 rounded-xl bg-transparent dark:hover:bg-white/5 hover:bg-black/5 transition font-medium text-sm flex items-center space-x-1"
										type="button"
										on:click={() => {}}
									>
										<Plus className="size-3.5" />
									</button>
								</Tooltip>
							</div> -->
						</div>
					</div>
				</div>

				<hr class=" border-gray-100 dark:border-gray-700/10 mt-1.5 mb-2.5 w-full" />

				<div class="flex flex-col gap-2 mb-1 px-0.5">
					{#if accessGroups.length > 0}
						{#each accessGroups as group}
							<div class="flex items-center gap-3 justify-between text-xs w-full transition">
								<div class="flex items-center gap-1.5 w-full font-medium">
									<div>
										<UserCircleSolid className="size-4" />
									</div>

									<div>
										{group.name}
									</div>
								</div>

								<div class="w-full flex justify-end items-center gap-0.5">
									<button
										class=""
										type="button"
										on:click={() => {
											if (accessRoles.includes('write')) {
												if (writeGroupIds.includes(group.id)) {
													accessControl.write.group_ids = writeGroupIds.filter(
														(group_id) => group_id !== group.id
													);
												} else {
													accessControl.write.group_ids = [...writeGroupIds, group.id];
												}
												onChange(accessControl);
											}
										}}
									>
										{#if writeGroupIds.includes(group.id)}
											<Badge type={'success'} content={$i18n.t('Write')} />
										{:else}
											<Badge type={'info'} content={$i18n.t('Read')} />
										{/if}
									</button>

									<button
										class=" rounded-full p-1 hover:bg-gray-100 dark:hover:bg-gray-850 transition"
										type="button"
										on:click={() => {
											accessControl.read.group_ids = readGroupIds.filter((id) => id !== group.id);
											onChange(accessControl);
										}}
									>
										<XMark />
									</button>
								</div>
							</div>
						{/each}
					{:else}
						<div class="flex items-center justify-center">
							<div class="text-gray-500 text-xs text-center py-2 px-10">
								{$i18n.t('No groups with access, add a group to grant access')}
							</div>
						</div>
					{/if}
				</div>
			</div>

			<div class="mt-3">
				<div class="text-sm font-semibold mb-1.5">{$i18n.t('Teams')}</div>
				<select
					class="outline-hidden bg-transparent text-sm rounded-lg block w-full pr-10 max-w-full dark:placeholder-gray-500"
					bind:value={selectedTeamId}
				>
					<option class=" text-gray-700" value="" disabled selected
						>{$i18n.t('Select a team')}</option
					>
					{#each userTeams.filter((team) => !(accessControl.read.team_ids ?? []).includes(team.id)) as team}
						<option class=" text-gray-700" value={team.id}>{team.name}</option>
					{/each}
				</select>
				<div class="flex flex-col gap-2 mt-2">
					{#each accessTeams as team}
						<div class="flex items-center gap-3 justify-between text-xs w-full">
							<div class="font-medium">{team.name}</div>
							<div class="flex items-center gap-0.5">
								<button
									type="button"
									on:click={() => {
										if (accessRoles.includes('write')) {
											if ((accessControl.write.team_ids ?? []).includes(team.id)) {
												accessControl.write.team_ids = accessControl.write.team_ids.filter(
													(id) => id !== team.id
												);
											} else {
												accessControl.write.team_ids = [
													...(accessControl.write.team_ids ?? []),
													team.id
												];
											}
											onChange(accessControl);
										}
									}}
								>
									{#if (accessControl.write.team_ids ?? []).includes(team.id)}
										<Badge type={'success'} content={$i18n.t('Write')} />
									{:else}
										<Badge type={'info'} content={$i18n.t('Read')} />
									{/if}
								</button>
								<button
									class=" rounded-full p-1 hover:bg-gray-100 dark:hover:bg-gray-850 transition"
									type="button"
									on:click={() => {
										accessControl.read.team_ids = (accessControl.read.team_ids ?? []).filter(
											(id) => id !== team.id
										);
										onChange(accessControl);
									}}
								>
									<XMark />
								</button>
							</div>
						</div>
					{/each}
				</div>
			</div>
		</div>
	{/if}
</div>
