<script lang="ts">
	import { getContext, onDestroy } from 'svelte';
	import { goto } from '$app/navigation';
	import { toast } from 'svelte-sonner';
	import { DropdownMenu } from 'bits-ui';
	import { activeOrganizationId, chatId, mobile, scheduledTasks, showSidebar } from '$lib/stores';
	import { runAutomationById } from '$lib/apis/automations';
	import { sortTasks, taskDot, type TaskSort } from '$lib/utils/scheduledTasks';
	import { loadScheduledTasks, markTaskSeen, setTaskPinned } from '$lib/utils/scheduledTaskStore';
	import { flyAndScale } from '$lib/utils/transitions';
	import Folder from '$lib/components/common/Folder.svelte';
	import Dropdown from '$lib/components/common/Dropdown.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import TaskDot from '$lib/components/scheduledTasks/TaskDot.svelte';
	import TaskImage from '$lib/components/scheduledTasks/TaskImage.svelte';
	import TaskMenu from '$lib/components/scheduledTasks/TaskMenu.svelte';
	import BarsArrowUp from '$lib/components/icons/BarsArrowUp.svelte';
	import Check from '$lib/components/icons/Check.svelte';

	const i18n = getContext('i18n');

	const readSetting = (key: string, fallback: string) => {
		try {
			return localStorage.getItem(key) ?? fallback;
		} catch {
			return fallback;
		}
	};
	const saveSetting = (key: string, value: string) => {
		try {
			localStorage.setItem(key, value);
		} catch {
			// Not remembered in this browser.
		}
	};

	let open = readSetting('showScheduledTasks', 'true') === 'true';
	let sortBy = readSetting('scheduledTaskSort', 'recent') as TaskSort;
	let showSort = false;
	// A clock tick, so dots on week-old runs disappear without a reload.
	let now = Date.now() / 1000;
	const clock = setInterval(() => (now = Date.now() / 1000), 60_000);
	onDestroy(() => clearInterval(clock));

	$: sortOptions = [
		{ value: 'recent', label: $i18n.t('Recently run') },
		{ value: 'name', label: $i18n.t('Name') },
		{ value: 'created', label: $i18n.t('Newest') }
	] as { value: TaskSort; label: string }[];

	let loadedOrg = null;
	$: if ($activeOrganizationId && $activeOrganizationId !== loadedOrg) {
		loadedOrg = $activeOrganizationId;
		scheduledTasks.set(null);
		loadScheduledTasks(localStorage.token);
	}

	$: pinned = sortTasks(
		($scheduledTasks ?? []).filter((task) => task.pinned),
		sortBy
	);

	const closeOnMobile = () => {
		if ($mobile) showSidebar.set(false);
	};

	const openTask = async (task) => {
		closeOnMobile();
		const run = task.last_run;
		if (!run?.chat_id) {
			goto(`/scheduled-tasks/${task.id}`);
			return;
		}
		await markTaskSeen(localStorage.token, task);
		goto(`/c/${run.chat_id}`);
	};

	const runNow = async (task) => {
		try {
			const run = await runAutomationById(localStorage.token, task.id);
			toast.success($i18n.t('Run started'));
			closeOnMobile();
			if (run?.chat_id) goto(`/c/${run.chat_id}`);
		} catch (error) {
			toast.error(`${error}`);
		}
	};
</script>

{#if pinned.length > 0}
	<Folder
		bind:open
		className="px-2 mt-0.5 mb-3"
		name={$i18n.t('Scheduled tasks')}
		emphasis="strong"
		dragAndDrop={false}
		on:change={(e) => saveSetting('showScheduledTasks', String(e.detail))}
	>
		<div slot="actions">
			<Dropdown bind:show={showSort}>
				<Tooltip content={$i18n.t('Sort')}>
					<button
						class="p-0.5 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-850"
						aria-label={$i18n.t('Sort scheduled tasks')}
					>
						<BarsArrowUp className="size-3.5" strokeWidth="2" />
					</button>
				</Tooltip>
				<div slot="content">
					<DropdownMenu.Content
						class="w-full max-w-[180px] rounded-xl px-1 py-1.5 z-50 bg-white dark:bg-gray-850 dark:text-white shadow-lg"
						sideOffset={-2}
						side="bottom"
						align="end"
						transition={flyAndScale}
					>
						{#each sortOptions as option (option.value)}
							<DropdownMenu.Item
								class="flex gap-2 items-center justify-between px-3 py-1.5 text-sm cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800 rounded-md"
								on:click={() => {
									sortBy = option.value;
									saveSetting('scheduledTaskSort', sortBy);
								}}
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
		</div>

		<div
			class="ml-3 pl-1 mt-[1px] flex flex-col max-h-48 overflow-y-auto border-s border-gray-100 dark:border-gray-900"
		>
			{#each pinned as task (task.id)}
				{@const dot = taskDot(task, now)}
				{@const current = task.last_run?.chat_id && task.last_run.chat_id === $chatId}
				<div
					class="group flex items-center gap-1 rounded-lg px-2 py-[5px] text-sm {current
						? 'bg-gray-100 dark:bg-gray-900'
						: 'hover:bg-gray-100 dark:hover:bg-gray-900'}"
				>
					<button
						class="flex-1 min-w-0 flex items-center gap-2 text-left"
						on:click={() => openTask(task)}
					>
						<TaskImage {task} className="size-5 rounded text-[10px]" />
						<span class="truncate">{task.name}</span>
						<TaskDot {dot} />
					</button>
					<div class="invisible group-hover:visible shrink-0 flex items-center">
						<TaskMenu
							pinned={task.pinned}
							onPin={(value) => setTaskPinned(localStorage.token, task.id, value)}
							onRun={() => runNow(task)}
							onEdit={() => {
								closeOnMobile();
								goto(`/scheduled-tasks/${task.id}`);
							}}
						>
							<button
								aria-label={$i18n.t('Scheduled task menu')}
								class="self-center dark:hover:text-white transition"
							>
								<svg
									xmlns="http://www.w3.org/2000/svg"
									viewBox="0 0 16 16"
									fill="currentColor"
									class="w-4 h-4"
								>
									<path
										d="M2 8a1.5 1.5 0 1 1 3 0 1.5 1.5 0 0 1-3 0ZM6.5 8a1.5 1.5 0 1 1 3 0 1.5 1.5 0 0 1-3 0ZM12.5 6.5a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3Z"
									/>
								</svg>
							</button>
						</TaskMenu>
					</div>
				</div>
			{/each}
		</div>
	</Folder>
{/if}
