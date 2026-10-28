<script lang="ts">
	import { getContext, onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { toast } from 'svelte-sonner';
	import {
		organizations,
		activeOrganizationId,
		user,
		WEBUI_NAME,
		showSidebar,
		scheduledTasks
	} from '$lib/stores';
	import { runAutomationById, updateAutomationById } from '$lib/apis/automations';
	import { canManageTask, describeSchedule, taskDot } from '$lib/utils/scheduledTasks';
	import { loadScheduledTasks, setTaskPinned } from '$lib/utils/scheduledTaskStore';
	import TaskDot from '$lib/components/scheduledTasks/TaskDot.svelte';
	import TaskImage from '$lib/components/scheduledTasks/TaskImage.svelte';
	import Switch from '$lib/components/common/Switch.svelte';
	import MenuLines from '$lib/components/icons/MenuLines.svelte';

	const i18n = getContext('i18n');

	$: tasks = $scheduledTasks ?? [];
	$: loaded = $scheduledTasks !== null;

	$: currentOrg = ($organizations ?? []).find((org) => org.id === $activeOrganizationId);
	$: isPersonal =
		!currentOrg || currentOrg.kind === 'personal' || $activeOrganizationId === $user?.id;
	$: sections = isPersonal
		? [{ title: $i18n.t('Private'), items: tasks }]
		: [
				{
					title: $i18n.t('Private'),
					items: tasks.filter((t) => t.visibility !== 'organization')
				},
				{
					title: $i18n.t('Organization'),
					items: tasks.filter((t) => t.visibility === 'organization')
				}
			];

	const refresh = () => loadScheduledTasks(localStorage.token);

	const setEnabled = async (task, enabled: boolean) => {
		if (task.enabled === enabled) return;
		try {
			await updateAutomationById(localStorage.token, task.id, { enabled });
			await refresh();
		} catch (error) {
			toast.error(`${error}`);
		}
	};

	const runNow = async (task) => {
		try {
			const run = await runAutomationById(localStorage.token, task.id);
			toast.success($i18n.t('Run started'));
			if (run?.chat_id) goto(`/c/${run.chat_id}`);
		} catch (error) {
			toast.error(`${error}`);
		}
	};

	onMount(refresh);
</script>

<svelte:head>
	<title>{$i18n.t('Scheduled tasks')} | {$WEBUI_NAME}</title>
</svelte:head>

<div class="flex flex-col w-full h-screen max-h-[100dvh]">
	<nav class="px-2.5 pt-1 backdrop-blur-xl">
		<div class="flex items-center justify-between">
			<div class="flex items-center gap-1">
				<div class="{$showSidebar ? 'md:hidden' : ''} self-center flex flex-none items-center">
					<button
						class="cursor-pointer p-1.5 flex rounded-xl hover:bg-gray-100 dark:hover:bg-gray-850 transition"
						on:click={() => showSidebar.set(!$showSidebar)}
					>
						<MenuLines />
					</button>
				</div>
				<div class="text-lg font-medium px-1.5">{$i18n.t('Scheduled tasks')}</div>
			</div>
			<a
				class="mr-2 rounded-lg bg-gray-900 dark:bg-white text-white dark:text-gray-900 px-3 py-1.5 text-sm"
				href="/scheduled-tasks/new"
			>
				{$i18n.t('New scheduled task')}
			</a>
		</div>
	</nav>

	<div class="flex-1 overflow-y-auto px-4 py-4 max-w-4xl w-full mx-auto flex flex-col gap-4">
		{#if loaded && tasks.length === 0}
			<div class="text-sm text-gray-500 text-center py-8">
				{$i18n.t(
					'No scheduled tasks yet. Create one, or ask in a chat to run a task on a schedule.'
				)}
			</div>
		{/if}

		{#each sections as section}
			{#if section.items.length > 0}
				<section class="flex flex-col gap-2">
					<div class="text-xs font-medium text-gray-500 uppercase tracking-wide">
						{section.title}
					</div>
					{#each section.items as task (task.id)}
						<div
							class="rounded-xl border border-gray-100 dark:border-gray-850 p-4 flex items-start justify-between gap-3"
						>
							<a class="min-w-0 flex-1 flex gap-3" href={`/scheduled-tasks/${task.id}`}>
								<TaskImage {task} className="size-14 rounded-lg text-lg" />
								<div class="min-w-0 flex-1">
								<div class="flex items-center gap-2 font-medium">
									<span class="truncate">{task.name}</span>
									<TaskDot dot={taskDot(task)} />
								</div>
								<div class="text-xs text-gray-500" title={task.cron ?? ''}>
									{task.cron ? describeSchedule(task.cron) : $i18n.t('Runs only when started')}
								</div>
								<div class="text-xs text-gray-500 mt-1 line-clamp-2">{task.prompt}</div>
								</div>
							</a>
							<div class="flex items-center gap-3 text-xs shrink-0">
								<button
									class="text-gray-500"
									on:click={() => setTaskPinned(localStorage.token, task.id, !task.pinned)}
								>
									{task.pinned ? $i18n.t('Unpin') : $i18n.t('Pin to sidebar')}
								</button>
								{#if canManageTask(task, $user?.id, currentOrg?.role)}
									<Switch state={task.enabled} on:change={(e) => setEnabled(task, e.detail)} />
								{/if}
								<button class="text-gray-900 dark:text-white" on:click={() => runNow(task)}>
									{$i18n.t('Run now')}
								</button>
							</div>
						</div>
					{/each}
				</section>
			{/if}
		{/each}
	</div>
</div>
