<script lang="ts">
	import { getContext, onDestroy } from 'svelte';
	import { goto } from '$app/navigation';
	import { activeOrganizationId, chatId, mobile, scheduledTasks, showSidebar } from '$lib/stores';
	import { sortTasks, taskDot, type TaskSort } from '$lib/utils/scheduledTasks';
	import { loadScheduledTasks, markTaskSeen, setTaskPinned } from '$lib/utils/scheduledTaskStore';
	import TaskDot from '$lib/components/scheduledTasks/TaskDot.svelte';
	import TaskImage from '$lib/components/scheduledTasks/TaskImage.svelte';
	import ChevronDown from '$lib/components/icons/ChevronDown.svelte';
	import ChevronRight from '$lib/components/icons/ChevronRight.svelte';
	import Pencil from '$lib/components/icons/Pencil.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';

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
	// A clock tick, so dots on week-old runs disappear without a reload.
	let now = Date.now() / 1000;
	const clock = setInterval(() => (now = Date.now() / 1000), 60_000);
	onDestroy(() => clearInterval(clock));

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

	const openTask = async (task) => {
		if ($mobile) showSidebar.set(false);
		const run = task.last_run;
		if (!run?.chat_id) {
			goto(`/scheduled-tasks/${task.id}`);
			return;
		}
		await markTaskSeen(localStorage.token, task);
		goto(`/c/${run.chat_id}`);
	};
</script>

{#if pinned.length > 0}
	<div class="px-2 mt-0.5">
		<div class="flex items-center justify-between gap-1 px-1.5 py-1">
			<button
				class="flex items-center gap-1 text-xs font-medium text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200"
				aria-expanded={open}
				on:click={() => {
					open = !open;
					saveSetting('showScheduledTasks', String(open));
				}}
			>
				{#if open}
					<ChevronDown className="size-3" strokeWidth="2.5" />
				{:else}
					<ChevronRight className="size-3" strokeWidth="2.5" />
				{/if}
				{$i18n.t('Scheduled tasks')}
			</button>
			{#if open}
				<select
					class="bg-transparent text-xs text-gray-500 dark:text-gray-400 outline-hidden cursor-pointer"
					aria-label={$i18n.t('Sort scheduled tasks')}
					bind:value={sortBy}
					on:change={() => saveSetting('scheduledTaskSort', sortBy)}
				>
					<option value="recent">{$i18n.t('Recently run')}</option>
					<option value="name">{$i18n.t('Name')}</option>
					<option value="created">{$i18n.t('Newest')}</option>
				</select>
			{/if}
		</div>

		{#if open}
			<div
				class="ml-3 pl-1 flex flex-col max-h-48 overflow-y-auto border-s border-gray-100 dark:border-gray-900"
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
						<div class="hidden group-hover:flex items-center gap-0.5 shrink-0 text-gray-500">
							<Tooltip content={$i18n.t('Edit')}>
								<button
									class="p-0.5 rounded hover:text-gray-800 dark:hover:text-gray-100"
									aria-label={$i18n.t('Edit')}
									on:click={() => goto(`/scheduled-tasks/${task.id}`)}
								>
									<Pencil className="size-3.5" />
								</button>
							</Tooltip>
							<Tooltip content={$i18n.t('Remove from sidebar')}>
								<button
									class="p-0.5 rounded hover:text-gray-800 dark:hover:text-gray-100"
									aria-label={$i18n.t('Remove from sidebar')}
									on:click={() => setTaskPinned(localStorage.token, task.id, false)}
								>
									<XMark className="size-3.5" />
								</button>
							</Tooltip>
						</div>
					</div>
				{/each}
			</div>
		{/if}
	</div>
{/if}
