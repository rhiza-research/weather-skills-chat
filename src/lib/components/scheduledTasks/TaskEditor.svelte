<script lang="ts">
	import { getContext, onMount } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { config, models, tools, user } from '$lib/stores';
	import { getToolSummary } from '$lib/apis/tools';
	import { createAutomation, updateAutomationById } from '$lib/apis/automations';
	import { taskToolIds } from '$lib/utils/toolDisplay';

	import ToolServersModal from '$lib/components/chat/ToolServersModal.svelte';
	import Wrench from '$lib/components/icons/Wrench.svelte';
	import GlobeAlt from '$lib/components/icons/GlobeAlt.svelte';
	import CommandLine from '$lib/components/icons/CommandLine.svelte';
	import Photo from '$lib/components/icons/Photo.svelte';

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

	function fromTask(source) {
		return {
			name: source?.name ?? '',
			prompt: source?.prompt ?? '',
			model: source?.model ?? '',
			cron: source?.cron ?? 'every day at noon',
			visibility: source?.visibility ?? 'private',
			source_chat_id: source?.source_chat_id ?? null,
			tool_ids: source?.tool_ids ?? null,
			features: { ...(source?.features ?? {}) }
		};
	}

	const allowed = (feature: string, configFlag: string) =>
		!!$config?.features?.[configFlag] &&
		($user?.role === 'admin' || !!$user?.permissions?.features?.[feature]);

	$: featureToggles = [
		{
			key: 'web_search',
			label: $i18n.t('Web search'),
			icon: GlobeAlt,
			shown: allowed('web_search', 'enable_web_search')
		},
		{
			key: 'code_interpreter',
			label: $i18n.t('Run code'),
			icon: CommandLine,
			shown: allowed('code_interpreter', 'enable_code_interpreter')
		},
		{
			key: 'image_generation',
			label: $i18n.t('Generate images'),
			icon: Photo,
			shown: allowed('image_generation', 'enable_image_generation')
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
				features: form.features
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
			onSaved(saved);
		} catch (error) {
			toast.error(`${error}`);
		} finally {
			saving = false;
		}
	};
</script>

<ToolServersModal bind:show={showTools} bind:selectedToolIds />

<form class="flex flex-col gap-3" on:submit|preventDefault={save}>
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

	<div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
		<label class="flex flex-col gap-1">
			<span class="text-xs font-medium text-gray-500">{$i18n.t('Schedule')}</span>
			<input
				class="rounded-lg bg-gray-50 dark:bg-gray-850 px-3 py-2 text-sm outline-hidden"
				placeholder={$i18n.t('every day at noon, or 0 12 * * *')}
				bind:value={form.cron}
				disabled={!canManage}
			/>
		</label>

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
	</div>

	<div class="flex flex-col gap-1">
		<span class="text-xs font-medium text-gray-500">{$i18n.t('Tools')}</span>
		<div class="flex flex-wrap items-center gap-1.5">
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
					{toggle.label}
				</button>
			{/each}
		</div>
	</div>

	{#if !isPersonal}
		<div>
			<select
				class="rounded-lg bg-gray-50 dark:bg-gray-850 px-3 py-1.5 text-sm"
				bind:value={form.visibility}
				disabled={!canManage}
			>
				<option value="private">{$i18n.t('Private')}</option>
				<option value="organization">{$i18n.t('Shared with the organization')}</option>
			</select>
		</div>
	{/if}

	{#if task?.cron}
		<div class="text-xs text-gray-500">
			{$i18n.t('Runs on cron')} <code>{task.cron}</code>
		</div>
	{/if}

	{#if canManage}
		<div>
			<button
				class="rounded-lg bg-gray-900 dark:bg-white text-white dark:text-gray-900 px-3 py-1.5 text-sm disabled:opacity-50"
				type="submit"
				disabled={saving}
			>
				{task ? $i18n.t('Save') : $i18n.t('Create')}
			</button>
		</div>
	{/if}
</form>
