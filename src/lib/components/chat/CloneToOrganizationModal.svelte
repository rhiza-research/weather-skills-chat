<script lang="ts">
	import { getContext } from 'svelte';
	import { toast } from 'svelte-sonner';

	import { cloneChatById } from '$lib/apis/chats';
	import { activeOrganizationId, organizations, user } from '$lib/stores';
	import Modal from '$lib/components/common/Modal.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';
	import User from '$lib/components/icons/User.svelte';
	import ChevronRight from '$lib/components/icons/ChevronRight.svelte';

	const i18n = getContext('i18n');

	export let show = false;
	export let chatId: string;
	export let title = '';

	let cloning = false;

	$: targets = ($organizations ?? []).filter((org) => org.id !== $activeOrganizationId);

	const cloneTo = async (orgId: string) => {
		cloning = true;
		const res = await cloneChatById(
			localStorage.token,
			chatId,
			$i18n.t('Clone of {{TITLE}}', { TITLE: title }),
			orgId
		).catch((error) => {
			toast.error(`${error}`);
			return null;
		});
		if (!res) {
			cloning = false;
			return;
		}
		// Reload into the target organization with the clone open.
		localStorage.setItem('activeOrganizationId', orgId);
		window.location.href = `/c/${res.id}`;
	};
</script>

<Modal size="sm" bind:show>
	<div>
		<div class="flex justify-between dark:text-gray-300 px-5 py-4">
			<div class="modal-title">
				{$i18n.t('Clone chat to another organization')}
			</div>
			<button
				class="self-center"
				aria-label={$i18n.t('Close')}
				on:click={() => {
					show = false;
				}}
			>
				<XMark className="size-5" />
			</button>
		</div>
		<hr class="border-line" />

		<div class="px-5 py-4 dark:text-gray-200">
			<div class="mb-2 text-sm text-muted">
				{$i18n.t('The copy is private to you. You will be switched to that organization.')}
			</div>
			<div class="flex flex-col gap-1 max-h-64 overflow-y-auto" aria-busy={cloning}>
				{#each targets as org (org.id)}
					<button
						class="flex items-center gap-2 rounded-xl py-1.5 px-3 w-full text-left text-sm hover:bg-black/5 dark:hover:bg-white/5 transition disabled:opacity-50"
						disabled={cloning}
						on:click={() => cloneTo(org.id)}
					>
						{#if org.logo}
							<img src={org.logo} alt="" class="size-5 rounded-full object-cover shrink-0" />
						{:else if org.kind === 'personal' || org.id === $user?.id}
							<User className="size-5 shrink-0" />
						{:else}
							<span class="size-5 shrink-0" />
						{/if}
						<span class="truncate flex-1">{org.name}</span>
						<ChevronRight className="size-4 shrink-0 text-subtle" strokeWidth="2" />
					</button>
				{/each}
			</div>
		</div>
	</div>
</Modal>
