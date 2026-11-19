<script lang="ts">
	import { onMount, getContext } from 'svelte';
	import { goto } from '$app/navigation';

	import { WEBUI_NAME, showSidebar, organizations, activeOrganizationId } from '$lib/stores';
	import { isWorkspaceManagerContext } from '$lib/utils/organizationContext';
	import MenuLines from '$lib/components/icons/MenuLines.svelte';
	import { page } from '$app/stores';

	const i18n = getContext('i18n');

	let loaded = false;

	$: currentOrg = ($organizations ?? []).find((org) => org.id === $activeOrganizationId);
	$: canManage = isWorkspaceManagerContext(currentOrg);

	onMount(async () => {
		if (!canManage) {
			await goto('/');
		}
		loaded = true;
	});

	$: if (loaded && !canManage) {
		goto('/');
	}
</script>

<svelte:head>
	<title>
		{$i18n.t('Organization settings')} | {$WEBUI_NAME}
	</title>
</svelte:head>

{#if loaded && canManage}
	<div
		class=" flex flex-col w-full h-screen max-h-[100dvh] transition-width duration-200 ease-in-out {$showSidebar
			? 'md:max-w-[calc(100%-260px)]'
			: ''} max-w-full"
	>
		<nav class="page-nav drag-region">
			<div class=" flex items-center gap-1">
				<div class="{$showSidebar ? 'md:hidden' : ''} flex flex-none items-center">
					<button
						id="sidebar-toggle-button"
						class="btn-ghost"
						on:click={() => {
							showSidebar.set(!$showSidebar);
						}}
						aria-label={$i18n.t('Toggle Sidebar')}
					>
						<div class=" m-auto self-center">
							<MenuLines />
						</div>
					</button>
				</div>

				<div class=" flex w-full">
					<div
						class="flex gap-1 scrollbar-none overflow-x-auto w-fit text-center text-sm font-medium rounded-full bg-transparent"
					>
						<a
							class="tab {['/organization', '/organization/membership'].includes(
								$page.url.pathname
							)
								? ''
								: 'tab-idle'}"
							href="/organization">{$i18n.t('Organization membership')}</a
						>
						<a
							class="tab {$page.url.pathname.includes(
								'/organization/settings'
							)
								? ''
								: 'tab-idle'}"
							href="/organization/settings">{$i18n.t('Organization settings')}</a
						>
					</div>
				</div>
			</div>
		</nav>

		<div class="page-body">
			<slot />
		</div>
	</div>
{/if}
