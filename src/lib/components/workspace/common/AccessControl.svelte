<script lang="ts">
	import { getContext, onMount } from 'svelte';

	const i18n = getContext('i18n');

	import { getOrganizations } from '$lib/apis/organizations';
	import UserCircleSolid from '$lib/components/icons/UserCircleSolid.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';
	import Badge from '$lib/components/common/Badge.svelte';

	export let onChange: Function = () => {};

	export let accessRoles = ['read'];
	export let accessControl = {};

	export let allowPublic = true;

	let selectedOrgId = '';
	let userOrgs = [];

	/** Expand private `{}` / partial ACLs so the template can safely read .read/.write. */
	const emptyAclForm = () => ({
		read: {
			group_ids: [],
			organization_ids: [],
			user_ids: []
		},
		write: {
			group_ids: [],
			organization_ids: [],
			user_ids: []
		}
	});

	const normalizeAclForm = (acl) => {
		if (acl === null) return null;
		return {
			read: {
				group_ids: acl?.read?.group_ids ?? [],
				organization_ids: acl?.read?.organization_ids ?? acl?.read?.team_ids ?? [],
				user_ids: acl?.read?.user_ids ?? []
			},
			write: {
				group_ids: acl?.write?.group_ids ?? [],
				organization_ids: acl?.write?.organization_ids ?? acl?.write?.team_ids ?? [],
				user_ids: acl?.write?.user_ids ?? []
			}
		};
	};

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
		userOrgs = await getOrganizations(localStorage.token).catch(() => []);

		if (accessControl === null) {
			if (!allowPublic) {
				accessControl = emptyAclForm();
				onChange(accessControl);
			}
		} else {
			accessControl = normalizeAclForm(accessControl);
		}
	});

	$: if (selectedOrgId) {
		onSelectOrg();
	}

	$: accessOrgs = userOrgs.filter((org) =>
		(accessControl?.read?.organization_ids ?? []).includes(org.id)
	);

	const onSelectOrg = () => {
		if (selectedOrgId !== '' && accessControl) {
			accessControl = normalizeAclForm(accessControl);
			accessControl.read.organization_ids = [
				...(accessControl.read.organization_ids ?? []),
				selectedOrgId
			];
			selectedOrgId = '';
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
									organization_ids: [],
									user_ids: []
								},
								write: {
									group_ids: [],
									organization_ids: [],
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
						{$i18n.t('Only selected users and organizations with permission can access')}
					{:else}
						{$i18n.t('Accessible to all users')}
					{/if}
				</div>
			</div>
		</div>
	</div>
	{#if accessControl !== null}
		{@const writeOrgIds = accessControl?.write?.organization_ids ?? []}
		<div>
			<div class="text-sm font-semibold mb-1.5">{$i18n.t('Organizations')}</div>
			<select
				class="outline-hidden bg-transparent text-sm rounded-lg block w-full pr-10 max-w-full dark:placeholder-gray-500"
				bind:value={selectedOrgId}
			>
				<option class=" text-gray-700" value="" disabled selected
					>{$i18n.t('Select an organization')}</option
				>
				{#each userOrgs.filter((org) => org.kind !== 'personal' && !(accessControl.read.organization_ids ?? []).includes(org.id)) as org}
					<option class=" text-gray-700" value={org.id}>{org.name}</option>
				{/each}
			</select>
			<div class="flex flex-col gap-2 mt-2">
				{#if accessOrgs.length > 0}
					{#each accessOrgs as org}
						<div class="flex items-center gap-3 justify-between text-xs w-full">
							<div class="flex items-center gap-1.5 font-medium">
								<UserCircleSolid className="size-4" />
								{org.name}
							</div>
							<div class="flex items-center gap-0.5">
								<button
									type="button"
									on:click={() => {
										if (accessRoles.includes('write')) {
											if (writeOrgIds.includes(org.id)) {
												accessControl.write.organization_ids = writeOrgIds.filter(
													(id) => id !== org.id
												);
											} else {
												accessControl.write.organization_ids = [...writeOrgIds, org.id];
											}
											onChange(accessControl);
										}
									}}
								>
									{#if writeOrgIds.includes(org.id)}
										<Badge type={'success'} content={$i18n.t('Write')} />
									{:else}
										<Badge type={'info'} content={$i18n.t('Read')} />
									{/if}
								</button>
								<button
									class=" rounded-full p-1 hover:bg-gray-100 dark:hover:bg-gray-850 transition"
									type="button"
									on:click={() => {
										accessControl.read.organization_ids = (
											accessControl.read.organization_ids ?? []
										).filter((id) => id !== org.id);
										accessControl.write.organization_ids = (
											accessControl.write.organization_ids ?? []
										).filter((id) => id !== org.id);
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
							{$i18n.t('No organizations with access, add an organization to grant access')}
						</div>
					</div>
				{/if}
			</div>
		</div>
	{/if}
</div>
