<script lang="ts">
	import { DropdownMenu } from 'bits-ui';
	import { createEventDispatcher, getContext } from 'svelte';
	import { toast } from 'svelte-sonner';

	import ArchiveBox from '$lib/components/icons/ArchiveBox.svelte';
	import Check from '$lib/components/icons/Check.svelte';
	import ChevronDown from '$lib/components/icons/ChevronDown.svelte';
	import Plus from '$lib/components/icons/Plus.svelte';
	import UsersSolid from '$lib/components/icons/UsersSolid.svelte';
	import {
		showSettings,
		activeUserIds,
		USAGE_POOL,
		mobile,
		showSidebar,
		user,
		config,
		organizations,
		activeOrganizationId
	} from '$lib/stores';
	import { fade } from 'svelte/transition';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import { userSignOut } from '$lib/apis/auths';
	import { createOrganization } from '$lib/apis/organizations';
	import { getMyUsage } from '$lib/apis/usage';
	import { isWorkspaceManagerContext } from '$lib/utils/organizationContext';
	import { formatUsd, usageBarPercent } from '$lib/utils/usage';

	const i18n = getContext('i18n');

	export let show = false;
	export let role = '';
	export let className = 'max-w-[280px]';

	const dispatch = createEventDispatcher();

	let showOrgPicker = false;
	let showRequestForm = false;
	let requestName = '';
	let requestDescription = '';
	let requesting = false;
	let usage = null;

	$: currentOrg =
		($organizations ?? []).find((org) => org.id === $activeOrganizationId) ?? {
			id: $user?.id,
			name: 'Personal',
			kind: 'personal'
		};
	$: isOrgManager = isWorkspaceManagerContext(currentOrg);

	const loadUsage = async () => {
		if (!localStorage.token) {
			usage = null;
			return;
		}
		try {
			usage = await getMyUsage(localStorage.token);
		} catch {
			usage = null;
		}
	};

	const resetOrgUi = () => {
		showOrgPicker = false;
		showRequestForm = false;
		requestName = '';
		requestDescription = '';
	};

	const closeMenu = () => {
		show = false;
		resetOrgUi();
		if ($mobile) {
			showSidebar.set(false);
		}
	};

	const selectOrg = (orgId: string) => {
		dispatch('switch-org', orgId);
		closeMenu();
	};

	const submitRequest = async () => {
		if (!requestName.trim()) {
			toast.error($i18n.t('Organization name cannot be empty.'));
			return;
		}
		requesting = true;
		try {
			await createOrganization(localStorage.token, {
				name: requestName.trim(),
				description: requestDescription.trim()
			});
			toast.success($i18n.t('Organization request submitted. An admin will activate it.'));
			requestName = '';
			requestDescription = '';
			showRequestForm = false;
		} catch (error) {
			toast.error(`${error}`);
		}
		requesting = false;
	};
</script>

<DropdownMenu.Root
	bind:open={show}
	onOpenChange={(state) => {
		if (state) {
			loadUsage();
		} else {
			resetOrgUi();
		}
		dispatch('change', state);
	}}
>
	<DropdownMenu.Trigger>
		<slot />
	</DropdownMenu.Trigger>

	<slot name="content">
		<DropdownMenu.Content
			class="w-full {className} text-sm rounded-xl px-1 py-1.5 z-50 bg-white dark:bg-gray-850 dark:text-white shadow-lg font-primary"
			sideOffset={8}
			side="bottom"
			align="start"
			transition={(e) => fade(e, { duration: 100 })}
		>
			<button
				class="flex items-center rounded-md py-2 px-3 w-full hover:bg-gray-50 dark:hover:bg-gray-800 transition"
				on:click={(e) => {
					e.preventDefault();
					e.stopPropagation();
					showOrgPicker = !showOrgPicker;
					if (!showOrgPicker) {
						showRequestForm = false;
					}
				}}
			>
				<div class="flex-1 text-left min-w-0">
					{#if showOrgPicker}
						<div class="truncate font-medium">{$i18n.t('Organizations')}</div>
					{:else}
						<div class="text-[11px] uppercase tracking-wide text-gray-400">
							{$i18n.t('Organization')}
						</div>
						<div class="truncate font-medium">{currentOrg.name}</div>
					{/if}
				</div>
				<ChevronDown
					className="size-4 text-gray-400 shrink-0 transition {showOrgPicker ? 'rotate-180' : ''}"
					strokeWidth="2"
				/>
			</button>

			{#if showOrgPicker}
				<div class="px-1 pb-1">
					{#each $organizations ?? [] as org}
						<button
							class="flex items-center gap-2 rounded-md py-1.5 px-3 w-full text-left hover:bg-gray-50 dark:hover:bg-gray-800 transition {org.id ===
							$activeOrganizationId
								? 'bg-gray-50 dark:bg-gray-800 font-medium'
								: 'text-gray-600 dark:text-gray-300'}"
							on:click={() => selectOrg(org.id)}
						>
							<span class="truncate flex-1">{org.name}</span>
							{#if org.id === $activeOrganizationId}
								<Check className="size-4 shrink-0" strokeWidth="2.5" />
							{/if}
						</button>
					{/each}
					<button
						class="flex items-center gap-2 rounded-md py-1.5 px-3 w-full text-left hover:bg-gray-50 dark:hover:bg-gray-800 transition text-gray-600 dark:text-gray-300"
						on:click={(e) => {
							e.preventDefault();
							e.stopPropagation();
							showRequestForm = !showRequestForm;
						}}
					>
						<Plus className="size-4" strokeWidth="2" />
						{$i18n.t('Request a new organization')}
					</button>
					{#if showRequestForm}
						<form
							class="px-3 pb-2 pt-1 flex flex-col gap-2"
							on:submit|preventDefault={submitRequest}
							on:click|stopPropagation
						>
							<input
								class="w-full rounded-lg bg-gray-50 dark:bg-gray-800 px-2.5 py-1.5 text-sm outline-hidden"
								placeholder={$i18n.t('Organization name')}
								bind:value={requestName}
								required
							/>
							<textarea
								class="w-full rounded-lg bg-gray-50 dark:bg-gray-800 px-2.5 py-1.5 text-sm outline-hidden"
								placeholder={$i18n.t('Description')}
								rows="2"
								bind:value={requestDescription}
							/>
							<button
								class="self-start rounded-lg bg-gray-900 dark:bg-white text-white dark:text-gray-900 px-2.5 py-1 text-xs"
								type="submit"
								disabled={requesting}
							>
								{$i18n.t('Submit request')}
							</button>
						</form>
					{/if}
				</div>
			{/if}

			{#if usage}
				<hr class="border-gray-100 dark:border-gray-850 my-1 p-0" />
				<div class="px-3 py-2">
					<div class="text-[11px] uppercase tracking-wide text-gray-400 truncate">
						{#if currentOrg.kind === 'personal'}
							{$i18n.t('Personal usage')}
						{:else}
							{$i18n.t('{{name}} usage', {
								name: usage.organization_name || currentOrg.name
							})}
						{/if}
					</div>
					<div class="text-xs font-medium tabular-nums">
						{formatUsd(usage.cost_usd, '$0.00')}{#if usage.effective_limit_usd != null}
							/ {formatUsd(usage.effective_limit_usd)}{/if}
					</div>
					{#if usage.effective_limit_usd != null}
						<div class="mt-1 h-1.5 rounded-full bg-gray-100 dark:bg-gray-800 overflow-hidden">
							<div
								class="h-full rounded-full {usage.over_limit
									? 'bg-red-500'
									: 'bg-gray-900 dark:bg-white'}"
								style="width: {usageBarPercent(
									usage.cost_usd,
									usage.effective_limit_usd,
									usage.over_limit
								)}%"
							></div>
						</div>
					{/if}
					{#if usage.over_limit && usage.message}
						<div class="mt-1 text-[11px] text-red-600 leading-snug">{usage.message}</div>
					{/if}
				</div>
			{/if}

			<hr class="border-gray-100 dark:border-gray-850 my-1 p-0" />

			<button
				class="flex rounded-md py-2 px-3 w-full hover:bg-gray-50 dark:hover:bg-gray-800 transition"
				on:click={async () => {
					await showSettings.set(true);
					closeMenu();
				}}
			>
					<div class=" self-center mr-3">
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
								d="M10.343 3.94c.09-.542.56-.94 1.11-.94h1.093c.55 0 1.02.398 1.11.94l.149.894c.07.424.384.764.78.93.398.164.855.142 1.205-.108l.737-.527a1.125 1.125 0 011.45.12l.773.774c.39.389.44 1.002.12 1.45l-.527.737c-.25.35-.272.806-.107 1.204.165.397.505.71.93.78l.893.15c.543.09.94.56.94 1.109v1.094c0 .55-.397 1.02-.94 1.11l-.893.149c-.425.07-.765.383-.93.78-.165.398-.143.854.107 1.204l.527.738c.32.447.269 1.06-.12 1.45l-.774.773a1.125 1.125 0 01-1.449.12l-.738-.527c-.35-.25-.806-.272-1.203-.107-.397.165-.71.505-.781.929l-.149.894c-.09.542-.56.94-1.11.94h-1.094c-.55 0-1.019-.398-1.11-.94l-.148-.894c-.071-.424-.384-.764-.781-.93-.398-.164-.854-.142-1.204.108l-.738.527c-.447.32-1.06.269-1.45-.12l-.773-.774a1.125 1.125 0 01-.12-1.45l.527-.737c.25-.35.273-.806.108-1.204-.165-.397-.505-.71-.93-.78l-.894-.15c-.542-.09-.94-.56-.94-1.109v-1.094c0-.55.398-1.02.94-1.11l.894-.149c.424-.07.765-.383.93-.78.165-.398.143-.854-.107-1.204l-.527-.738a1.125 1.125 0 01.12-1.45l.773-.773a1.125 1.125 0 011.45-.12l.737.527c.35.25.807.272 1.204.107.397-.165.71.505.78-.929l.15-.894z"
							/>
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"
							/>
						</svg>
					</div>
					<div class=" self-center truncate">{$i18n.t('Settings')}</div>
			</button>

			{#if isOrgManager}
				<a
					class="flex rounded-md py-2 px-3 w-full hover:bg-gray-50 dark:hover:bg-gray-800 transition"
					href="/organization"
					on:click={closeMenu}
				>
					<div class=" self-center mr-3">
						<UsersSolid className="w-5 h-5" />
					</div>
					<div class=" self-center truncate">{$i18n.t('Organization settings')}</div>
				</a>
			{/if}

			<button
				class="flex rounded-md py-2 px-3 w-full hover:bg-gray-50 dark:hover:bg-gray-800 transition"
				on:click={() => {
					dispatch('show', 'archived-chat');
					closeMenu();
				}}
			>
				<div class=" self-center mr-3">
					<ArchiveBox className="size-5" strokeWidth="1.5" />
				</div>
				<div class=" self-center truncate">{$i18n.t('Archived Chats')}</div>
			</button>

			{#if role === 'admin'}
				<a
					class="flex rounded-md py-2 px-3 w-full hover:bg-gray-50 dark:hover:bg-gray-800 transition"
					href="/admin"
					on:click={closeMenu}
				>
					<div class=" self-center mr-3">
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
								d="M17.982 18.725A7.488 7.488 0 0012 15.75a7.488 7.488 0 00-5.982 2.975m11.963 0a9 9 0 10-11.963 0m11.963 0A8.966 8.966 0 0112 21a8.966 8.966 0 01-5.982-2.275M15 9.75a3 3 0 11-6 0 3 3 0 016 0z"
							/>
						</svg>
					</div>
					<div class=" self-center truncate">{$i18n.t('Admin Panel')}</div>
				</a>
			{/if}

			<hr class=" border-gray-100 dark:border-gray-850 my-1 p-0" />

			<button
				class="flex rounded-md py-2 px-3 w-full hover:bg-gray-50 dark:hover:bg-gray-800 transition"
				on:click={async () => {
					try {
						await userSignOut();
					} catch (err) {
						console.error(err);
					}
					user.set(null);

					localStorage.removeItem('token');
					location.href = '/auth';

					show = false;
					resetOrgUi();
				}}
			>
				<div class=" self-center mr-3">
					<svg
						xmlns="http://www.w3.org/2000/svg"
						viewBox="0 0 20 20"
						fill="currentColor"
						class="w-5 h-5"
					>
						<path
							fill-rule="evenodd"
							d="M3 4.25A2.25 2.25 0 015.25 2h5.5A2.25 2.25 0 0113 4.25v2a.75.75 0 01-1.5 0v-2a.75.75 0 00-.75-.75h-5.5a.75.75 0 00-.75.75v11.5c0 .414.336.75.75.75h5.5a.75.75 0 00.75-.75v-2a.75.75 0 011.5 0v2A2.25 2.25 0 0110.75 18h-5.5A2.25 2.25 0 013 15.75V4.25z"
							clip-rule="evenodd"
						/>
						<path
							fill-rule="evenodd"
							d="M6 10a.75.75 0 01.75-.75h9.546l-1.048-.943a.75.75 0 111.004-1.114l2.5 2.25a.75.75 0 010 1.114l-2.5 2.25a.75.75 0 11-1.004-1.114l1.048-.943H6.75A.75.75 0 016 10z"
							clip-rule="evenodd"
						/>
					</svg>
				</div>
				<div class=" self-center truncate">{$i18n.t('Sign Out')}</div>
			</button>

			{#if $activeUserIds?.length > 0}
				<hr class=" border-gray-100 dark:border-gray-850 my-1 p-0" />

				<Tooltip
					content={$USAGE_POOL && $USAGE_POOL.length > 0
						? `${$i18n.t('Running')}: ${$USAGE_POOL.join(', ')} ✨`
						: ''}
				>
					<div class="flex rounded-md py-1.5 px-3 text-xs gap-2.5 items-center">
						<div class=" flex items-center">
							<span class="relative flex size-2">
								<span
									class="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75"
								/>
								<span class="relative inline-flex rounded-full size-2 bg-green-500" />
							</span>
						</div>

						<div class=" ">
							<span class="">
								{$i18n.t('Active Users')}:
							</span>
							<span class=" font-semibold">
								{$activeUserIds?.length}
							</span>
						</div>
					</div>
				</Tooltip>
			{/if}

			{#if $config?.image_tag}
				<div class="px-3 py-1.5 text-[10px] leading-none text-gray-400 dark:text-gray-500 select-all">
					version {$config.image_tag}
				</div>
			{/if}

			<!-- <DropdownMenu.Item class="flex items-center px-3 py-2 text-sm ">
				<div class="flex items-center">Profile</div>
			</DropdownMenu.Item> -->
		</DropdownMenu.Content>
	</slot>
</DropdownMenu.Root>
