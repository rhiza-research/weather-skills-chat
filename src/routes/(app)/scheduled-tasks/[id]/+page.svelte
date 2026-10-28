<script lang="ts">
	import { getContext, onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { toast } from 'svelte-sonner';
	import { organizations, activeOrganizationId, user, WEBUI_NAME, showSidebar } from '$lib/stores';
	import {
		deleteAutomationById,
		getAutomationById,
		getAutomationRuns,
		runAutomationById
	} from '$lib/apis/automations';
	import { getChatById } from '$lib/apis/chats';
	import { canManageTask, taskFromChat } from '$lib/utils/scheduledTasks';
	import TaskEditor from '$lib/components/scheduledTasks/TaskEditor.svelte';
	import MenuLines from '$lib/components/icons/MenuLines.svelte';
	import ArrowLeft from '$lib/components/icons/ArrowLeft.svelte';

	const i18n = getContext('i18n');

	let task = null;
	let prefill = null;
	let runs = [];
	let loaded = false;

	$: id = $page.params.id;
	$: isNew = id === 'new';
	$: currentOrg = ($organizations ?? []).find((org) => org.id === $activeOrganizationId);
	$: isPersonal =
		!currentOrg || currentOrg.kind === 'personal' || $activeOrganizationId === $user?.id;
	$: canManage = canManageTask(task, $user?.id, currentOrg?.role);

	const load = async (taskId: string) => {
		loaded = false;
		task = null;
		prefill = null;
		runs = [];
		if (taskId === 'new') {
			const from = $page.url.searchParams.get('from');
			if (from) {
				const chat = await getChatById(localStorage.token, from).catch(() => null);
				if (chat) prefill = taskFromChat(from, chat);
			}
		} else {
			task = await getAutomationById(localStorage.token, taskId).catch((error) => {
				toast.error(`${error}`);
				return null;
			});
			if (!task) {
				goto('/scheduled-tasks');
				return;
			}
			runs = await getAutomationRuns(localStorage.token, taskId).catch(() => []);
		}
		loaded = true;
	};

	let loadedId = null;
	$: if (id !== loadedId) {
		loadedId = id;
		load(id);
	}

	const runNow = async () => {
		try {
			const run = await runAutomationById(localStorage.token, task.id);
			toast.success($i18n.t('Run started'));
			if (run?.chat_id) goto(`/c/${run.chat_id}`);
		} catch (error) {
			toast.error(`${error}`);
		}
	};

	const remove = async () => {
		if (!confirm($i18n.t('Delete this scheduled task and its run history?'))) return;
		try {
			await deleteAutomationById(localStorage.token, task.id);
			goto('/scheduled-tasks');
		} catch (error) {
			toast.error(`${error}`);
		}
	};

	const statusClass = (status: string) =>
		({
			success: 'text-green-600 dark:text-green-400',
			failure: 'text-red-600 dark:text-red-400',
			error: 'text-red-600 dark:text-red-400',
			unknown: 'text-orange-500 dark:text-orange-400'
		})[status] ?? 'text-gray-500';
</script>

<svelte:head>
	<title>
		{task?.name ?? $i18n.t('New scheduled task')} | {$WEBUI_NAME}
	</title>
</svelte:head>

<div class="flex flex-col w-full h-screen max-h-[100dvh]">
	<nav class="px-2.5 pt-1 backdrop-blur-xl">
		<div class="flex items-center justify-between gap-2">
			<div class="flex items-center gap-1 min-w-0">
				<div class="{$showSidebar ? 'md:hidden' : ''} self-center flex flex-none items-center">
					<button
						class="cursor-pointer p-1.5 flex rounded-xl hover:bg-gray-100 dark:hover:bg-gray-850 transition"
						on:click={() => showSidebar.set(!$showSidebar)}
					>
						<MenuLines />
					</button>
				</div>
				<a
					class="p-1.5 flex rounded-xl hover:bg-gray-100 dark:hover:bg-gray-850 transition"
					href="/scheduled-tasks"
					aria-label={$i18n.t('Scheduled tasks')}
				>
					<ArrowLeft className="size-4" />
				</a>
				<div class="text-lg font-medium px-1.5 truncate">
					{isNew ? $i18n.t('New scheduled task') : (task?.name ?? '')}
				</div>
			</div>
			{#if task}
				<div class="flex items-center gap-2 mr-2 text-sm shrink-0">
					{#if canManage}
						<button class="text-red-500" on:click={remove}>{$i18n.t('Delete')}</button>
					{/if}
					<button
						class="rounded-lg bg-gray-900 dark:bg-white text-white dark:text-gray-900 px-3 py-1.5"
						on:click={runNow}
					>
						{$i18n.t('Run now')}
					</button>
				</div>
			{/if}
		</div>
	</nav>

	<div class="flex-1 overflow-y-auto px-4 py-4 max-w-3xl w-full mx-auto flex flex-col gap-6">
		{#if loaded}
			{#key task?.id ?? 'new'}
				<TaskEditor
					{task}
					{prefill}
					{isPersonal}
					{canManage}
					onSaved={(saved) => {
						if (isNew) goto(`/scheduled-tasks/${saved.id}`);
						else task = saved;
					}}
				/>
			{/key}

			{#if task}
				<section class="flex flex-col gap-1">
					<div class="text-xs font-medium text-gray-500">{$i18n.t('Runs')}</div>
					{#each runs as run (run.id)}
						<button
							class="text-left text-sm px-2 py-1.5 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-850 flex justify-between gap-3 disabled:cursor-default"
							disabled={!run.chat_id}
							on:click={() => goto(`/c/${run.chat_id}`)}
						>
							<span class="min-w-0">
								<span class={statusClass(run.status)}>{run.status}</span>
								{#if run.summary}
									<span class="text-gray-600 dark:text-gray-300"> · {run.summary}</span>
								{/if}
								{#if run.error}
									<span class="text-gray-500"> · {run.error}</span>
								{/if}
							</span>
							<span class="text-xs text-gray-400 shrink-0">
								{run.started_at ? new Date(run.started_at * 1000).toLocaleString() : ''}
							</span>
						</button>
					{:else}
						<div class="text-xs text-gray-400 px-2">{$i18n.t('No runs yet')}</div>
					{/each}
				</section>
			{/if}
		{/if}
	</div>
</div>
