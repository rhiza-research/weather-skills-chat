<script lang="ts">
	import { onMount, getContext } from 'svelte';
	import { WEBUI_NAME, showSidebar, user } from '$lib/stores';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';

	import MenuLines from '$lib/components/icons/MenuLines.svelte';

	const i18n = getContext('i18n');

	let loaded = false;

	onMount(async () => {
		if ($user?.role !== 'admin') {
			if ($page.url.pathname.includes('/prompts') && !$user?.permissions?.workspace?.prompts) {
				goto('/');
			} else if ($page.url.pathname.includes('/tools') && !$user?.permissions?.workspace?.tools) {
				goto('/');
			}
		}

		loaded = true;
	});
</script>

<svelte:head>
	<title>
		{$i18n.t('Workspace')} | {$WEBUI_NAME}
	</title>
</svelte:head>

{#if loaded}
	<div
		class=" relative flex flex-col w-full h-screen max-h-[100dvh] transition-width duration-200 ease-in-out {$showSidebar
			? 'md:max-w-[calc(100%-260px)]'
			: ''} max-w-full"
	>
		<nav class="page-nav drag-region">
			<div class=" flex items-center gap-1">
				<div class="{$showSidebar ? 'md:hidden' : ''} self-center flex flex-none items-center">
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

				<div class="">
					<div
						class="flex gap-1 scrollbar-none overflow-x-auto w-fit text-center text-sm font-medium rounded-full bg-transparent touch-auto pointer-events-auto"
					>
						<a
							class="tab {$page.url.pathname.includes(
								'/workspace/models'
							)
								? ''
								: 'tab-idle'}"
							href="/workspace/models">{$i18n.t('Models')}</a
						>

						<a
							class="tab {$page.url.pathname.includes('/workspace/skills')
								? ''
								: 'tab-idle'}"
							href="/workspace/skills"
						>
							{$i18n.t('Skills')}
						</a>

						<a
							class="tab {$page.url.pathname.includes('/workspace/secrets')
								? ''
								: 'tab-idle'}"
							href="/workspace/secrets"
						>
							{$i18n.t('Secrets')}
						</a>

						<a
							class="tab {$page.url.pathname.includes(
								'/workspace/preferences'
							)
								? ''
								: 'tab-idle'}"
							href="/workspace/preferences"
						>
							{$i18n.t('Preferences')}
						</a>
					</div>
				</div>

				<!-- <div class="flex items-center text-xl font-semibold">{$i18n.t('Workspace')}</div> -->
			</div>
		</nav>

		<div class="page-body" id="workspace-container">
			<slot />
		</div>
	</div>
{/if}
