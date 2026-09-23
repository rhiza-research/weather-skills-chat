<script>
	import { toast } from 'svelte-sonner';
	import { getContext, onMount } from 'svelte';

	import { goto } from '$app/navigation';
	import { user } from '$lib/stores';

	import { getUsers, getUserDefaultPermissions, updateUserDefaultPermissions } from '$lib/apis/users';

	import UserList from './Users/UserList.svelte';
	import GroupModal from './Users/Groups/EditGroupModal.svelte';
	import UsersSolid from '$lib/components/icons/UsersSolid.svelte';
	import ChevronRight from '$lib/components/icons/ChevronRight.svelte';

	const i18n = getContext('i18n');

	let users = [];
	let loaded = false;
	let showDefaultPermissionsModal = false;
	let defaultPermissions = {
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
			stt: true,
			tts: true,
			call: true,
			multiple_models: true,
			temporary: true,
			temporary_enforced: false
		},
		features: {
			direct_tool_servers: false,
			web_search: true,
			image_generation: true,
			code_interpreter: true
		}
	};

	const updateDefaultPermissionsHandler = async (group) => {
		const res = await updateUserDefaultPermissions(localStorage.token, group.permissions).catch(
			(error) => {
				toast.error(`${error}`);
				return null;
			}
		);

		if (res) {
			toast.success($i18n.t('Default permissions updated successfully'));
			defaultPermissions = await getUserDefaultPermissions(localStorage.token);
		}
	};

	onMount(async () => {
		if ($user?.role !== 'admin') {
			await goto('/');
		} else {
			users = await getUsers(localStorage.token);
			defaultPermissions = await getUserDefaultPermissions(localStorage.token);
		}
		loaded = true;
	});
</script>

{#if loaded}
	<div class="flex flex-col w-full h-full min-w-0 pb-2">
		<div class="flex-1 min-w-0 overflow-x-hidden overflow-y-auto">
			<UserList {users} />

			<hr class="mb-2 mt-3 border-gray-100 dark:border-gray-850" />

			<GroupModal
				bind:show={showDefaultPermissionsModal}
				tabs={['permissions']}
				bind:permissions={defaultPermissions}
				custom={false}
				onSubmit={updateDefaultPermissionsHandler}
			/>

			<button
				class="flex items-center justify-between rounded-lg w-full transition pt-1"
				on:click={() => {
					showDefaultPermissionsModal = true;
				}}
			>
				<div class="flex items-center gap-2.5">
					<div class="p-1.5 bg-black/5 dark:bg-white/10 rounded-full">
						<UsersSolid className="size-4" />
					</div>

					<div class="text-left">
						<div class=" text-sm font-medium">{$i18n.t('Default permissions')}</div>

						<div class="flex text-xs mt-0.5">
							{$i18n.t('applies to all users with the "user" role')}
						</div>
					</div>
				</div>

				<div>
					<ChevronRight strokeWidth="2.5" />
				</div>
			</button>
		</div>
	</div>
{/if}
