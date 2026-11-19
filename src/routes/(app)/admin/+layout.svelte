<script lang="ts">
	import { onMount, getContext } from 'svelte';
	import { goto } from '$app/navigation';

	import { WEBUI_NAME, organizations, showSidebar, user } from '$lib/stores';
	import MenuLines from '$lib/components/icons/MenuLines.svelte';
	import { page } from '$app/stores';
	import { platformAdminMembership } from '$lib/utils/organizationContext';

	const i18n = getContext('i18n');

	let loaded = false;

	onMount(async () => {
		if ($user?.role !== 'admin') {
			// A platform admin who opens an admin link in another organization
			// reloads into the platform organization instead of being sent away.
			const platform = platformAdminMembership($organizations);
			if (platform?.id && localStorage.getItem('activeOrganizationId') !== platform.id) {
				localStorage.setItem('activeOrganizationId', platform.id);
				location.reload();
				return;
			}
			await goto('/');
		}
		loaded = true;
	});

	$: if (loaded && $user && $user.role !== 'admin') {
		goto('/');
	}
</script>

<svelte:head>
	<title>
		{$i18n.t('Admin Panel')} | {$WEBUI_NAME}
	</title>
</svelte:head>

{#if loaded}
	<div
		class=" flex flex-col w-full h-screen max-h-[100dvh] transition-width duration-200 ease-in-out {$showSidebar
			? 'md:max-w-[calc(100%-260px)]'
			: ''} max-w-full"
	>
		<nav class="   px-2.5 pt-1 backdrop-blur-xl drag-region">
			<div class=" flex items-center gap-1">
				<div class="{$showSidebar ? 'md:hidden' : ''} flex flex-none items-center self-end">
					<button
						id="sidebar-toggle-button"
						class="btn-ghost btn-ghost-sm"
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
						class="flex gap-1 scrollbar-none overflow-x-auto w-fit text-center text-sm font-medium rounded-full bg-transparent pt-1"
					>
						<a
							class="tab {['/admin', '/admin/users'].includes(
								$page.url.pathname
							)
								? ''
								: 'tab-idle'}"
							href="/admin">{$i18n.t('Users and Organizations')}</a
						>

						<a
							class="tab {$page.url.pathname.includes(
								'/admin/membership'
							)
								? ''
								: 'tab-idle'}"
							href="/admin/membership">{$i18n.t('Platform organization membership')}</a
						>

						<a
							class="tab {$page.url.pathname.includes('/admin/settings')
								? ''
								: 'tab-idle'}"
							href="/admin/settings">{$i18n.t('Admin settings')}</a
						>

						<a
							class="tab {$page.url.pathname.includes('/admin/models')
								? ''
								: 'tab-idle'}"
							href="/admin/models">{$i18n.t('Model catalog')}</a
						>

						<a
							class="tab {$page.url.pathname.includes('/admin/skills')
								? ''
								: 'tab-idle'}"
							href="/admin/skills">{$i18n.t('Skill catalog')}</a
						>

						<a
							class="tab {$page.url.pathname.includes('/admin/knowledge')
								? ''
								: 'tab-idle'}"
							href="/admin/knowledge">{$i18n.t('Knowledge catalog')}</a
						>
					</div>
				</div>
			</div>
		</nav>

		<div class=" pb-1 px-[16px] flex-1 min-w-0 max-h-full overflow-y-auto">
			<slot />
		</div>
	</div>
{/if}
