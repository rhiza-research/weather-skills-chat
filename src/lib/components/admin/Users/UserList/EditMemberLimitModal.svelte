<script>
	import { toast } from 'svelte-sonner';
	import { createEventDispatcher, getContext } from 'svelte';

	import { updateOrganizationMemberLimit } from '$lib/apis/organizations';
	import { formatUsd } from '$lib/utils/usage';
	import Modal from '$lib/components/common/Modal.svelte';

	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher();

	export let show = false;
	export let orgId = '';
	export let member = null;
	export let orgLimit = null;

	let unlimited = false;
	let limitUsd = 300;
	let loading = false;
	let initialized = false;

	$: if (show && member && !initialized) {
		if (member.monthly_limit_usd == null) {
			unlimited = true;
			limitUsd = orgLimit == null ? 300 : Number(orgLimit);
		} else {
			unlimited = false;
			limitUsd = Number(member.monthly_limit_usd);
		}
		initialized = true;
	}
	$: if (!show) {
		initialized = false;
	}

	const submitHandler = async () => {
		if (!orgId || !member?.user_id) return;
		let monthlyLimit = null;
		if (!unlimited) {
			const parsed = Number(limitUsd);
			if (!Number.isFinite(parsed) || parsed < 0) {
				toast.error($i18n.t('Monthly usage limit must be a number greater than or equal to 0.'));
				return;
			}
			monthlyLimit = parsed;
		}
		loading = true;
		try {
			const org = await updateOrganizationMemberLimit(
				localStorage.token,
				orgId,
				member.user_id,
				monthlyLimit
			);
			dispatch('save', org);
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
			<div class=" text-lg font-medium self-center">{$i18n.t('Edit monthly usage limit')}</div>
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
				<div class="text-sm mb-3">
					{member?.name ?? member?.user_id ?? ''}
					{#if member?.email}
						<span class="text-gray-500">· {member.email}</span>
					{/if}
				</div>

				<div class="flex flex-col w-full">
					<div class=" mb-0.5 text-xs text-gray-500">{$i18n.t('Monthly usage limit')}</div>
					<label class="flex items-center gap-2 text-sm mt-1">
						<input type="checkbox" bind:checked={unlimited} />
						{$i18n.t('Unlimited')}
					</label>
					{#if !unlimited}
						<div class="flex items-center gap-1.5 mt-2">
							<span class="text-sm text-gray-500">$</span>
							<input
								class="w-full text-sm bg-transparent outline-hidden"
								type="number"
								min="0"
								step="0.01"
								bind:value={limitUsd}
								placeholder="300"
							/>
						</div>
					{/if}
					{#if orgLimit != null}
						<div class="text-xs text-gray-500 mt-2">
							{$i18n.t('Cannot exceed the organization monthly usage limit of {{limit}}.', {
								limit: formatUsd(orgLimit)
							})}
						</div>
					{/if}
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
