<script>
	import { toast } from 'svelte-sonner';
	import { createEventDispatcher, getContext } from 'svelte';

	import { updateOrganizationById } from '$lib/apis/organizations';
	import Modal from '$lib/components/common/Modal.svelte';
	import Textarea from '$lib/components/common/Textarea.svelte';

	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher();

	export let show = false;
	export let selectedOrg = null;

	let name = '';
	let description = '';
	let loading = false;

	$: if (show && selectedOrg) {
		name = selectedOrg.name ?? '';
		description = selectedOrg.description ?? '';
	}

	const submitHandler = async () => {
		if (!selectedOrg?.id || !name.trim()) {
			toast.error($i18n.t('Organization name cannot be empty.'));
			return;
		}
		loading = true;
		try {
			await updateOrganizationById(localStorage.token, selectedOrg.id, {
				name: name.trim(),
				description: description.trim()
			});
			dispatch('save');
			show = false;
		} catch (error) {
			toast.error(`${error}`);
		}
		loading = false;
	};
</script>

<Modal size="sm" bind:show>
	<div>
		<div class=" flex justify-between dark:text-gray-300 px-5 py-4">
			<div class=" text-lg font-medium self-center">{$i18n.t('Edit Organization')}</div>
			<button
				class="self-center"
				on:click={() => {
					show = false;
				}}
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					viewBox="0 0 20 20"
					fill="currentColor"
					class="w-5 h-5"
				>
					<path
						d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z"
					/>
				</svg>
			</button>
		</div>
		<hr class="border-gray-100 dark:border-gray-850" />

		<div class="flex flex-col w-full p-5 dark:text-gray-200">
			<form
				class="flex flex-col w-full"
				on:submit|preventDefault={() => {
					submitHandler();
				}}
			>
				<div class="flex flex-col w-full">
					<div class=" mb-0.5 text-xs text-gray-500">{$i18n.t('Name')}</div>
					<input
						class="w-full text-sm bg-transparent outline-hidden"
						type="text"
						bind:value={name}
						placeholder={$i18n.t('Organization name')}
						autocomplete="off"
						required
					/>
				</div>

				<div class="flex flex-col w-full mt-3">
					<div class=" mb-0.5 text-xs text-gray-500">{$i18n.t('Description')}</div>
					<Textarea
						className="w-full text-sm bg-transparent outline-hidden resize-none"
						rows={2}
						bind:value={description}
						placeholder={$i18n.t('Organization description')}
					/>
				</div>

				<div class="flex justify-end pt-4">
					<button
						class="px-3.5 py-1.5 text-sm font-medium bg-black hover:bg-gray-900 text-white dark:bg-white dark:text-black dark:hover:bg-gray-100 transition rounded-full disabled:opacity-50"
						type="submit"
						disabled={loading}
					>
						{$i18n.t('Save')}
					</button>
				</div>
			</form>
		</div>
	</div>
</Modal>
