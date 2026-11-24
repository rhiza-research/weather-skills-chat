<script>
	import XMarkSolid from '$lib/components/icons/XMarkSolid.svelte';
	import { toast } from 'svelte-sonner';
	import { createEventDispatcher, getContext } from 'svelte';

	import { updateOrganizationMemberLimit } from '$lib/apis/organizations';
	import { formatCreditAmount, formatUsd } from '$lib/utils/usage';
	import Modal from '$lib/components/common/Modal.svelte';

	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher();

	export let show = false;
	export let orgId = '';
	export let member = null;
	export let orgLimit = null;
	export let credits = false;

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
			<h2 class="modal-title">{$i18n.t('Edit monthly usage limit')}</h2>
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
		<hr class="border-line my-2" />

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
						<span class="text-muted">· {member.email}</span>
					{/if}
				</div>

				<div class="flex flex-col w-full">
					<div class="mb-0.5 text-xs text-muted">{$i18n.t('Monthly usage limit')}</div>
					<label class="flex items-center gap-2 text-sm mt-1">
						<input type="checkbox" bind:checked={unlimited} />
						{$i18n.t('Unlimited')}
					</label>
					{#if !unlimited}
						<div class="flex items-center gap-1.5 mt-2">
							{#if !credits}
								<span class="text-sm text-muted">$</span>
							{/if}
							<input
								class="w-full bg-transparent outline-hidden text-sm"
								type="number"
								min="0"
								step="0.01"
								bind:value={limitUsd}
								placeholder="300"
							/>
							{#if credits}
								<span class="text-sm text-muted shrink-0">{$i18n.t('credits')}</span>
							{/if}
						</div>
					{/if}
					{#if orgLimit != null}
						<div class="text-xs text-muted mt-2">
							{$i18n.t('Cannot exceed the organization monthly usage limit of {{limit}}.', {
								limit: credits
									? `${formatCreditAmount(orgLimit)} ${$i18n.t('credits')}`
									: formatUsd(orgLimit)
							})}
						</div>
					{/if}
				</div>

				<div class="flex justify-end pt-4">
					<button
						class="px-4 py-1.5 text-sm font-medium bg-inverse hover:bg-gray-900 text-on-inverse dark:hover:bg-gray-100 transition rounded-full disabled:opacity-50"
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
