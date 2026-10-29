<script lang="ts">
	import { getContext, onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { toast } from 'svelte-sonner';
	import { DropdownMenu } from 'bits-ui';
	import {
		organizations,
		activeOrganizationId,
		user,
		WEBUI_NAME,
		showSidebar,
		scheduledTasks
	} from '$lib/stores';
	import { runAutomationById, updateAutomationById } from '$lib/apis/automations';
	import {
		canManageTask,
		describeSchedule,
		sortTasks,
		taskDot,
		type TaskSort
	} from '$lib/utils/scheduledTasks';
	import { loadScheduledTasks, setTaskPinned } from '$lib/utils/scheduledTaskStore';
	import TaskDot from '$lib/components/scheduledTasks/TaskDot.svelte';
	import TaskImage from '$lib/components/scheduledTasks/TaskImage.svelte';
	import { flyAndScale } from '$lib/utils/transitions';
	import Switch from '$lib/components/common/Switch.svelte';
	import Dropdown from '$lib/components/common/Dropdown.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import MenuLines from '$lib/components/icons/MenuLines.svelte';
	import BarsArrowUp from '$lib/components/icons/BarsArrowUp.svelte';
	import Check from '$lib/components/icons/Check.svelte';

	const i18n = getContext('i18n');

	const SORT_KEY = 'scheduledTaskPageSort';
	let sortBy: TaskSort = 'recent';
	try {
		sortBy = (localStorage.getItem(SORT_KEY) as TaskSort) ?? 'recent';
	} catch {
		// Not remembered in this browser.
	}
	let showSort = false;

	const setSort = (value: TaskSort) => {
		sortBy = value;
		try {
			localStorage.setItem(SORT_KEY, value);
		} catch {
			// Not remembered in this browser.
		}
	};

	$: sortOptions = [
		{ value: 'recent', label: $i18n.t('Recently run') },
		{ value: 'updated', label: $i18n.t('Recently edited') },
		{ value: 'name', label: $i18n.t('Name') }
	] as { value: TaskSort; label: string }[];

	$: tasks = sortTasks($scheduledTasks ?? [], sortBy);
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
			<div class="flex items-center gap-1">
				<Dropdown bind:show={showSort}>
					<Tooltip content={$i18n.t('Sort')}>
						<button
							class="p-1.5 rounded-xl hover:bg-gray-100 dark:hover:bg-gray-850 transition"
							aria-label={$i18n.t('Sort scheduled tasks')}
						>
							<BarsArrowUp className="size-4" strokeWidth="2" />
						</button>
					</Tooltip>
					<div slot="content">
						<DropdownMenu.Content
							class="w-full max-w-[180px] rounded-xl px-1 py-1.5 z-50 bg-white dark:bg-gray-850 dark:text-white shadow-lg"
							sideOffset={4}
							side="bottom"
							align="end"
							transition={flyAndScale}
						>
							{#each sortOptions as option (option.value)}
								<DropdownMenu.Item
									class="flex gap-2 items-center justify-between px-3 py-1.5 text-sm cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800 rounded-md"
									on:click={() => setSort(option.value)}
								>
									{option.label}
									{#if sortBy === option.value}
										<Check className="size-3.5" strokeWidth="2.5" />
									{/if}
								</DropdownMenu.Item>
							{/each}
						</DropdownMenu.Content>
					</div>
				</Dropdown>
				<a
					class="mr-2 rounded-lg bg-gray-900 dark:bg-white text-white dark:text-gray-900 px-3 py-1.5 text-sm"
					href="/scheduled-tasks/new"
				>
					{$i18n.t('New scheduled task')}
				</a>
			</div>
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
							class="rounded-xl border border-gray-100 dark:border-gray-850 p-4 flex items-start justify-between gap-3 {task.enabled
								? ''
								: 'bg-gray-50 dark:bg-gray-900/50'}"
						>
							<a class="min-w-0 flex-1 flex gap-3" href={`/scheduled-tasks/${task.id}`}>
								<TaskImage {task} className="size-14 rounded-lg text-lg" />
								<div class="min-w-0 flex-1">
								<div class="flex items-center gap-2 font-medium">
									<span class="truncate {task.enabled ? '' : 'text-gray-400 dark:text-gray-500'}"
										>{task.name}</span
									>
									<TaskDot dot={taskDot(task)} />
								</div>
								<div class="text-xs text-gray-500" title={task.cron ?? ''}>
									{#if !task.enabled}
										<span
											class="mr-1 rounded px-1 py-px bg-gray-200 dark:bg-gray-800 text-gray-600 dark:text-gray-300"
										>
											{$i18n.t('Off')}
										</span>
									{/if}
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
