<script lang="ts">
	import { getContext, onMount } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { config, models, tools, user } from '$lib/stores';
	import { getToolSummary } from '$lib/apis/tools';
	import { createAutomation, previewSchedule, updateAutomationById } from '$lib/apis/automations';
	import { taskToolIds } from '$lib/utils/toolDisplay';
	import { describeSchedule } from '$lib/utils/scheduledTasks';

	import ToolServersModal from '$lib/components/chat/ToolServersModal.svelte';
	import Wrench from '$lib/components/icons/Wrench.svelte';
	import GlobeAlt from '$lib/components/icons/GlobeAlt.svelte';
	import CommandLine from '$lib/components/icons/CommandLine.svelte';
	import Eye from '$lib/components/icons/Eye.svelte';

	const i18n = getContext('i18n');

	/** The task to edit, or null for a new one. */
	export let task = null;
	/** Starting values for a new task, e.g. from a chat. */
	export let prefill = null;
	export let isPersonal = true;
	export let canManage = true;
	export let onSaved: (task) => void = () => {};

	let form = fromTask(task ?? prefill);
	let selectedToolIds: string[] = [];
	let toolsReady = false;
	let showTools = false;
	let saving = false;

	// A saved schedule shows as English until the user changes it. While
	// typing, the server's parser previews what it would save.
	let editingSchedule = !task?.cron;
	let showCron = false;
	let previewCron: string | null = task?.cron ?? null;
	let previewTimer: ReturnType<typeof setTimeout>;
	$: if (editingSchedule) schedulePreview(form.cron);

	const schedulePreview = (text: string) => {
		clearTimeout(previewTimer);
		previewTimer = setTimeout(async () => {
			previewCron = text?.trim()
				? await previewSchedule(localStorage.token, text).catch(() => null)
				: null;
		}, 300);
	};

	function fromTask(source) {
		return {
			name: source?.name ?? '',
			prompt: source?.prompt ?? '',
			model: source?.model ?? '',
			cron: source?.cron ?? 'every day at noon',
			visibility: source?.visibility ?? 'private',
			source_chat_id: source?.source_chat_id ?? null,
			tool_ids: source?.tool_ids ?? null,
			features: { ...(source?.features ?? {}) },
			timeout_minutes: source?.timeout_minutes ?? null
		};
	}

	const allowed = (feature: string, configFlag: string) =>
		!!$config?.features?.[configFlag] &&
		($user?.role === 'admin' || !!$user?.permissions?.features?.[feature]);

	// Worded as in the chat bar. A run has no one to ask, so reading files is
	// either allowed or not.
	$: featureToggles = [
		{
			key: 'web_search',
			on: $i18n.t('Agent allowed to search the web'),
			off: $i18n.t('Agent not allowed to search the web'),
			icon: GlobeAlt,
			shown: allowed('web_search', 'enable_web_search')
		},
		{
			key: 'code_interpreter',
			on: $i18n.t('Agent allowed to write/execute its own code'),
			off: $i18n.t('Agent not allowed to write/execute its own code'),
			icon: CommandLine,
			shown: allowed('code_interpreter', 'enable_code_interpreter')
		},
		{
			key: 'read_artifacts',
			on: $i18n.t('Agent allowed to read files'),
			off: $i18n.t('Agent not allowed to read files'),
			icon: Eye,
			shown: true
		}
	].filter((toggle) => toggle.shown || form.features?.[toggle.key]);

	const toggleFeature = (key: string) => {
		if (!canManage) return;
		form.features = { ...form.features, [key]: !form.features?.[key] };
	};

	onMount(async () => {
		if ($tools === null) {
			tools.set(await getToolSummary(localStorage.token).catch(() => []));
		}
		selectedToolIds = taskToolIds(form.tool_ids, $tools ?? []);
		toolsReady = true;
	});

	const when = (seconds: number) => new Date(seconds * 1000).toLocaleString();

	/** Who created the task, and who last changed it if anyone has, for the lines by Save. */
	const authorship = (t) => {
		const lines = [
			t.created_by_name
				? $i18n.t('Created by {{NAME}} {{WHEN}}', { NAME: t.created_by_name, WHEN: when(t.created_at) })
				: $i18n.t('Created {{WHEN}}', { WHEN: when(t.created_at) })
		];
		if (t.updated_at !== t.created_at) {
			lines.push(
				t.updated_by_name
					? $i18n.t('Last changed by {{NAME}} {{WHEN}}', {
							NAME: t.updated_by_name,
							WHEN: when(t.updated_at)
						})
					: $i18n.t('Last changed {{WHEN}}', { WHEN: when(t.updated_at) })
			);
		}
		return lines;
	};

	const save = async () => {
		saving = true;
		try {
			const payload = {
				name: form.name,
				prompt: form.prompt,
				model: form.model || null,
				cron: form.cron || '',
				visibility: isPersonal ? 'private' : form.visibility || 'private',
				tool_ids: toolsReady ? selectedToolIds : form.tool_ids,
				features: form.features,
				timeout_minutes:
					form.timeout_minutes == null || form.timeout_minutes === ''
						? null
						: Number(form.timeout_minutes)
			};
			const saved = task
				? await updateAutomationById(localStorage.token, task.id, payload)
				: await createAutomation(localStorage.token, {
						...payload,
						// New tasks start on; the Scheduled tasks page turns them on and off.
						enabled: true,
						source_chat_id: form.source_chat_id
					});
			toast.success(task ? $i18n.t('Scheduled task saved') : $i18n.t('Scheduled task created'));
			task = saved;
			form = fromTask(saved);
			editingSchedule = !saved?.cron;
			previewCron = saved?.cron ?? null;
			onSaved(saved);
		} catch (error) {
			toast.error(`${error}`);
		} finally {
			saving = false;
		}
	};
</script>

<!-- A run never gets the scheduled task tools, so only these can be switched. -->
<ToolServersModal
	bind:show={showTools}
	bind:selectedToolIds
	bind:builtinFeatures={form.features}
	builtinGroups={['email', 'preferences']}
/>

<form class="flex flex-col gap-4 max-w-xl" on:submit|preventDefault={save}>
	<label class="flex flex-col gap-1">
		<span class="text-xs font-medium text-gray-500">{$i18n.t('Name')}</span>
		<input
			class="rounded-lg bg-gray-50 dark:bg-gray-850 px-3 py-2 text-sm outline-hidden"
			bind:value={form.name}
			disabled={!canManage}
			required
		/>
	</label>

	<label class="flex flex-col gap-1">
		<span class="text-xs font-medium text-gray-500">{$i18n.t('Prompt')}</span>
		<textarea
			class="rounded-lg bg-gray-50 dark:bg-gray-850 px-3 py-2 text-sm outline-hidden"
			rows="6"
			placeholder={$i18n.t('What the task should do each time it runs')}
			bind:value={form.prompt}
			disabled={!canManage}
			required
		/>
	</label>

	<div class="flex flex-col gap-1">
		<span class="text-xs font-medium text-gray-500">{$i18n.t('Schedule')}</span>
		{#if editingSchedule}
			<input
				class="rounded-lg bg-gray-50 dark:bg-gray-850 px-3 py-2 text-sm outline-hidden"
				placeholder={$i18n.t('every weekday at 7am, or 0 7 * * 1-5')}
				aria-label={$i18n.t('Schedule')}
				bind:value={form.cron}
				disabled={!canManage}
			/>
		{:else}
			<div class="flex items-center gap-2 rounded-lg bg-gray-50 dark:bg-gray-850 px-3 py-2 text-sm">
				<span class="flex-1">{describeSchedule(form.cron)}</span>
				{#if canManage}
					<button
						type="button"
						class="text-xs text-gray-500 hover:text-gray-800 dark:hover:text-gray-100"
						on:click={() => (editingSchedule = true)}
					>
						{$i18n.t('Change')}
					</button>
				{/if}
			</div>
		{/if}
		<div class="flex items-center gap-2 text-xs text-gray-500 min-h-4">
			{#if editingSchedule && form.cron?.trim()}
				{#if previewCron}
					<span>{describeSchedule(previewCron)}</span>
				{:else}
					<span class="text-orange-500">
						{$i18n.t("Not understood. Try 'every weekday at 7am', 'mondays and thursdays at 6pm', or cron.")}
					</span>
				{/if}
			{/if}
			{#if previewCron || (!editingSchedule && form.cron)}
				<button
					type="button"
					class="ml-auto hover:text-gray-800 dark:hover:text-gray-100"
					on:click={() => (showCron = !showCron)}
				>
					{showCron ? $i18n.t('Hide cron') : $i18n.t('Show cron')}
				</button>
			{/if}
		</div>
		{#if showCron}
			<code class="text-xs text-gray-500">
				{editingSchedule ? (previewCron ?? '') : form.cron}
			</code>
		{/if}
	</div>

	<label class="flex flex-col gap-1">
		<span class="text-xs font-medium text-gray-500">{$i18n.t('Model')}</span>
		<select
			class="rounded-lg bg-gray-50 dark:bg-gray-850 px-3 py-2 text-sm"
			bind:value={form.model}
			disabled={!canManage}
		>
			<option value="">{$i18n.t('Default model')}</option>
			{#each $models as model}
				<option value={model.id}>{model.name ?? model.id}</option>
			{/each}
		</select>
	</label>

	<label class="flex flex-col gap-1">
		<span class="text-xs font-medium text-gray-500">{$i18n.t('Time limit (minutes)')}</span>
		<input
			class="rounded-lg bg-gray-50 dark:bg-gray-850 px-3 py-2 text-sm outline-hidden"
			type="number"
			min="1"
			max="1440"
			step="1"
			placeholder={$i18n.t('60 (default)')}
			bind:value={form.timeout_minutes}
			disabled={!canManage}
		/>
		<span class="text-xs text-gray-500">
			{$i18n.t('A run that takes longer is stopped and shown as an error.')}
		</span>
	</label>

	<div class="flex flex-col gap-1">
		<span class="text-xs font-medium text-gray-500">{$i18n.t('Tools')}</span>
		<div class="flex flex-col items-start gap-1.5">
			<button
				type="button"
				class="flex items-center gap-1.5 rounded-full border border-gray-200 dark:border-gray-800 px-2.5 py-1.5 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-850 transition disabled:opacity-50"
				disabled={!canManage || !toolsReady}
				on:click={() => (showTools = true)}
			>
				<Wrench className="size-4" strokeWidth="1.75" />
				{$i18n.t('{{COUNT}} tools', { COUNT: selectedToolIds.length })}
			</button>

			{#each featureToggles as toggle (toggle.key)}
				{@const on = !!form.features?.[toggle.key]}
				<button
					type="button"
					aria-pressed={on}
					disabled={!canManage}
					class="flex items-center gap-1.5 rounded-full border px-2.5 py-1.5 text-sm transition {on
						? 'bg-blue-100 dark:bg-blue-500/20 border-blue-400/20 text-blue-500 dark:text-blue-400'
						: 'border-gray-200 dark:border-gray-800 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-850'}"
					on:click={() => toggleFeature(toggle.key)}
				>
					<svelte:component this={toggle.icon} className="size-4" strokeWidth="1.75" />
					{on ? toggle.on : toggle.off}
				</button>
			{/each}
		</div>
	</div>

	{#if !isPersonal}
		<label class="flex flex-col gap-1">
			<span class="text-xs font-medium text-gray-500">{$i18n.t('Sharing')}</span>
			<select
				class="w-full rounded-lg bg-gray-50 dark:bg-gray-850 px-3 py-2 text-sm"
				bind:value={form.visibility}
				disabled={!canManage}
			>
				<option value="private">{$i18n.t('Private')}</option>
				<option value="organization">{$i18n.t('Shared with the organization')}</option>
			</select>
		</label>
	{/if}

	<div class="flex flex-wrap items-center gap-x-3 gap-y-1">
		{#if canManage}
			<button
				class="rounded-lg bg-gray-900 dark:bg-white text-white dark:text-gray-900 px-3 py-1.5 text-sm disabled:opacity-50"
				type="submit"
				disabled={saving}
			>
				{task ? $i18n.t('Save') : $i18n.t('Create')}
			</button>
		{/if}
		{#if task}
			<div class="flex flex-col text-xs text-gray-500">
				{#each authorship(task) as line}
					<span>{line}</span>
				{/each}
			</div>
		{/if}
	</div>
</form>
