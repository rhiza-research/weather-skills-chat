<script lang="ts">
	import Cog6Solid from '$lib/components/icons/Cog6Solid.svelte';
	import XMarkSolid from '$lib/components/icons/XMarkSolid.svelte';
	import { toast } from 'svelte-sonner';
	import { getContext, onMount } from 'svelte';
	const i18n = getContext('i18n');

	import Modal from '$lib/components/common/Modal.svelte';
	import Display from './Display.svelte';
	import Permissions from './Permissions.svelte';
	import Users from './Users.svelte';
	import UserPlusSolid from '$lib/components/icons/UserPlusSolid.svelte';
	import WrenchSolid from '$lib/components/icons/WrenchSolid.svelte';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';

	export let onSubmit: Function = () => {};
	export let onDelete: Function = () => {};

	export let show = false;
	export let edit = false;

	export let users = [];
	export let group = null;

	export let custom = true;

	export let tabs = ['general', 'permissions', 'users'];

	let selectedTab = 'general';
	let loading = false;
	let showDeleteConfirmDialog = false;

	export let name = '';
	export let description = '';

	export let permissions = {
		workspace: {
			models: false,
			knowledge: false,
			prompts: false,
			tools: false,
			skills: false
		},
		sharing: {
			public_models: false,
			public_knowledge: false,
			public_prompts: false,
			public_tools: false,
			public_skills: false
		},
		chat: {
			controls: true,
			file_upload: true,
			delete: true,
			edit: true,
			temporary: true
		},
		features: {
			direct_tool_servers: false,
			web_search: true,
			image_generation: true,
			code_interpreter: true
		}
	};
	export let userIds = [];

	const submitHandler = async () => {
		loading = true;

		const group = {
			name,
			description,
			permissions,
			user_ids: userIds
		};

		await onSubmit(group);

		loading = false;
		show = false;
	};

	const init = () => {
		if (group) {
			name = group.name;
			description = group.description;
			permissions = group?.permissions ?? {};

			userIds = group?.user_ids ?? [];
		}
	};

	$: if (show) {
		init();
	}

	onMount(() => {
		console.log(tabs);
		selectedTab = tabs[0];
		init();
	});
</script>

<ConfirmDialog
	bind:show={showDeleteConfirmDialog}
	on:confirm={() => {
		onDelete();
		show = false;
	}}
/>

<Modal size="md" bind:show>
	<div>
		<div class=" flex justify-between dark:text-gray-100 px-5 pt-4 mb-1.5">
			<h2 class="modal-title">
				{#if custom}
					{#if edit}
						{$i18n.t('Edit User Group')}
					{:else}
						{$i18n.t('Add User Group')}
					{/if}
				{:else}
					{$i18n.t('Edit Default Permissions')}
				{/if}
			</h2>
			<button
				class="self-center"
					aria-label={$i18n.t('Close')}
				on:click={() => {
					show = false;
				}}
			>
				<XMarkSolid className="size-5" />
			</button>
		</div>

		<div class="flex flex-col md:flex-row w-full px-4 pb-4 md:space-x-4 dark:text-gray-200">
			<div class=" flex flex-col w-full sm:flex-row sm:justify-center sm:space-x-6">
				<form
					class="flex flex-col w-full"
					on:submit={(e) => {
						e.preventDefault();
						submitHandler();
					}}
				>
					<div class="flex flex-col lg:flex-row w-full h-full pb-2 lg:space-x-4">
						<div
							id="admin-settings-tabs-container"
							class="tabs flex flex-row overflow-x-auto gap-2.5 max-w-full lg:gap-1 lg:flex-col lg:flex-none lg:w-40 dark:text-gray-200 text-sm font-medium text-left scrollbar-none"
						>
							{#if tabs.includes('general')}
								<button
									class="px-0.5 py-1 max-w-fit w-fit rounded-lg flex-1 lg:flex-none flex text-right transition {selectedTab ===
									'general'
										? ''
										: ' tab-idle'}"
									on:click={() => {
										selectedTab = 'general';
									}}
									type="button"
								>
									<div class=" self-center mr-2">
										<Cog6Solid className="size-4" />
									</div>
									<div class=" self-center">{$i18n.t('General')}</div>
								</button>
							{/if}

							{#if tabs.includes('permissions')}
								<button
									class="px-0.5 py-1 max-w-fit w-fit rounded-lg flex-1 lg:flex-none flex text-right transition {selectedTab ===
									'permissions'
										? ''
										: ' tab-idle'}"
									on:click={() => {
										selectedTab = 'permissions';
									}}
									type="button"
								>
									<div class=" self-center mr-2">
										<WrenchSolid />
									</div>
									<div class=" self-center">{$i18n.t('Permissions')}</div>
								</button>
							{/if}

							{#if tabs.includes('users')}
								<button
									class="px-0.5 py-1 max-w-fit w-fit rounded-lg flex-1 lg:flex-none flex text-right transition {selectedTab ===
									'users'
										? ''
										: ' tab-idle'}"
									on:click={() => {
										selectedTab = 'users';
									}}
									type="button"
								>
									<div class=" self-center mr-2">
										<UserPlusSolid />
									</div>
									<div class=" self-center">{$i18n.t('Users')} ({userIds.length})</div>
								</button>
							{/if}
						</div>

						<div
							class="flex-1 mt-1 lg:mt-1 lg:h-[22rem] lg:max-h-[22rem] overflow-y-auto scrollbar-hidden"
						>
							{#if selectedTab == 'general'}
								<Display bind:name bind:description />
							{:else if selectedTab == 'permissions'}
								<Permissions bind:permissions />
							{:else if selectedTab == 'users'}
								<Users bind:userIds {users} />
							{/if}
						</div>
					</div>

					<!-- <div
						class=" tabs flex flex-row overflow-x-auto gap-2.5 text-sm font-medium border-b border-b-gray-800 scrollbar-hidden"
					>
						{#if tabs.includes('display')}
							<button
								class="px-0.5 pb-1.5 min-w-fit flex text-right transition border-b-2 {selectedTab ===
								'display'
									? ' dark:border-white'
									: 'border-transparent tab-idle'}"
								on:click={() => {
									selectedTab = 'display';
								}}
								type="button"
							>
								{$i18n.t('Display')}
							</button>
						{/if}

						{#if tabs.includes('permissions')}
							<button
								class="px-0.5 pb-1.5 min-w-fit flex text-right transition border-b-2 {selectedTab ===
								'permissions'
									? '  dark:border-white'
									: 'border-transparent tab-idle'}"
								on:click={() => {
									selectedTab = 'permissions';
								}}
								type="button"
							>
								{$i18n.t('Permissions')}
							</button>
						{/if}

						{#if tabs.includes('users')}
							<button
								class="px-0.5 pb-1.5 min-w-fit flex text-right transition border-b-2 {selectedTab ===
								'users'
									? ' dark:border-white'
									: ' border-transparent tab-idle'}"
								on:click={() => {
									selectedTab = 'users';
								}}
								type="button"
							>
								{$i18n.t('Users')} ({userIds.length})
							</button>
						{/if}
					</div> -->

					<div class="flex justify-between pt-3 text-sm font-medium gap-1.5">
						{#if edit}
							<button
								class="px-4 py-1.5 text-sm font-medium dark:bg-black dark:hover:bg-gray-900 dark:text-white bg-white text-black hover:bg-gray-100 transition rounded-full flex flex-row space-x-1 items-center"
								type="button"
								on:click={() => {
									showDeleteConfirmDialog = true;
								}}
							>
								{$i18n.t('Delete')}
							</button>
						{:else}
							<div></div>
						{/if}

						<button
							class="px-4 py-1.5 text-sm font-medium bg-black hover:bg-gray-900 text-white dark:bg-white dark:text-black dark:hover:bg-gray-100 transition rounded-full flex flex-row space-x-1 items-center {loading
								? ' cursor-not-allowed'
								: ''}"
							type="submit"
							disabled={loading}
						>
							{$i18n.t('Save')}

							{#if loading}
								<div class="ml-2 self-center">
									<svg
										class=" size-4"
										viewBox="0 0 24 24"
										fill="currentColor"
										xmlns="http://www.w3.org/2000/svg"
										><style>
											.spinner_ajPY {
												transform-origin: center;
												animation: spinner_AtaB 0.75s infinite linear;
											}
											@keyframes spinner_AtaB {
												100% {
													transform: rotate(360deg);
												}
											}
										</style><path
											d="M12,1A11,11,0,1,0,23,12,11,11,0,0,0,12,1Zm0,19a8,8,0,1,1,8-8A8,8,0,0,1,12,20Z"
											opacity=".25"
										/><path
											d="M10.14,1.16a11,11,0,0,0-9,8.92A1.59,1.59,0,0,0,2.46,12,1.52,1.52,0,0,0,4.11,10.7a8,8,0,0,1,6.66-6.61A1.42,1.42,0,0,0,12,2.69h0A1.57,1.57,0,0,0,10.14,1.16Z"
											class="spinner_ajPY"
										/></svg
									>
								</div>
							{/if}
						</button>
					</div>
				</form>
			</div>
		</div>
	</div>
</Modal>
