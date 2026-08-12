<script lang="ts">
	import { onMount, getContext } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { toast } from 'svelte-sonner';
	import { teams, user, WEBUI_NAME, showSidebar, models } from '$lib/stores';
	import {
		createAutomation,
		deleteAutomationById,
		getAutomationRuns,
		getAutomations,
		runAutomationById,
		updateAutomationById
	} from '$lib/apis/automations';
	import { getChatById } from '$lib/apis/chats';
	import MenuLines from '$lib/components/icons/MenuLines.svelte';

	const i18n = getContext('i18n');

	let automations = [];
	let selected = null;
	let runs = [];
	let showForm = false;
	let editingId = null;
	let form = emptyForm();

	function emptyForm() {
		return {
			name: '',
			prompt: '',
			model: '',
			cron: 'every day at noon',
			enabled: true,
			team_id: '',
			source_chat_id: null,
			tool_ids: null,
			features: null
		};
	}

	function toolSettingsFromChatInput(chatId: string) {
		try {
			const raw = localStorage.getItem(`chat-input-${chatId}`);
			if (!raw) return { tool_ids: null, features: null };
			const input = JSON.parse(raw);
			const tool_ids = Array.isArray(input.selectedToolIds)
				? input.selectedToolIds.filter(Boolean)
				: null;
			const features = {
				web_search: !!input.webSearchEnabled,
				image_generation: !!input.imageGenerationEnabled,
				code_interpreter: !!input.codeInterpreterEnabled
			};
			return { tool_ids, features };
		} catch {
			return { tool_ids: null, features: null };
		}
	}

	$: sections = [
		{ title: $i18n.t('Personal'), items: automations.filter((a) => !a.team_id) },
		...($teams ?? []).map((team) => ({
			title: team.name,
			items: automations.filter((a) => a.team_id === team.id)
		}))
	].filter((section) => section.items.length);

	const canManage = (automation) => {
		if ($user?.role === 'admin') return true;
		if (automation.user_id === $user?.id) return true;
		const team = ($teams ?? []).find((t) => t.id === automation.team_id);
		return team?.role === 'admin';
	};

	const refresh = async () => {
		automations = await getAutomations(localStorage.token).catch((error) => {
			toast.error(`${error}`);
			return [];
		});
	};

	const prefillFromChat = async (chatId: string) => {
		const chat = await getChatById(localStorage.token, chatId).catch(() => null);
		if (!chat) return;
		const messages = chat?.chat?.messages ?? [];
		const userTurns = messages
			.filter((m) => m.role === 'user')
			.map((m) => m.content)
			.filter(Boolean);
		const tools = toolSettingsFromChatInput(chatId);
		form = {
			name: chat?.title || 'Scheduled chat',
			prompt: userTurns.join('\n\n') || chat?.title || '',
			model: chat?.chat?.models?.[0] || '',
			cron: 'every day at noon',
			enabled: true,
			team_id: chat?.team_id || '',
			source_chat_id: chatId,
			tool_ids: tools.tool_ids,
			features: tools.features
		};
		editingId = null;
		showForm = true;
	};

	const openRuns = async (automation) => {
		selected = automation;
		runs = await getAutomationRuns(localStorage.token, automation.id).catch(() => []);
	};

	const openEdit = (automation) => {
		editingId = automation.id;
		form = {
			name: automation.name,
			prompt: automation.prompt,
			model: automation.model || '',
			cron: automation.cron || '',
			enabled: automation.enabled,
			team_id: automation.team_id || '',
			source_chat_id: automation.source_chat_id,
			tool_ids: automation.tool_ids ?? null,
			features: automation.features ?? null
		};
		showForm = true;
	};

	const closeForm = () => {
		showForm = false;
		editingId = null;
		form = emptyForm();
	};

	const submit = async () => {
		try {
			const payload = {
				name: form.name,
				prompt: form.prompt,
				model: form.model || null,
				cron: form.cron || '',
				team_id: form.team_id || null,
				tool_ids: form.tool_ids,
				features: form.features
			};
			if (editingId) {
				await updateAutomationById(localStorage.token, editingId, payload);
				toast.success($i18n.t('Automation updated'));
			} else {
				await createAutomation(localStorage.token, {
					...payload,
					enabled: form.enabled,
					source_chat_id: form.source_chat_id
				});
			}
			closeForm();
			await refresh();
		} catch (error) {
			toast.error(`${error}`);
		}
	};

	const toggle = async (automation) => {
		try {
			await updateAutomationById(localStorage.token, automation.id, {
				enabled: !automation.enabled
			});
			await refresh();
		} catch (error) {
			toast.error(`${error}`);
		}
	};

	const runNow = async (automation) => {
		try {
			const run = await runAutomationById(localStorage.token, automation.id);
			toast.success($i18n.t('Run started'));
			if (run?.chat_id) {
				goto(`/c/${run.chat_id}`);
			} else {
				openRuns(automation);
			}
		} catch (error) {
			toast.error(`${error}`);
		}
	};

	const remove = async (automation) => {
		if (!confirm($i18n.t('Delete this automation?'))) return;
		try {
			await deleteAutomationById(localStorage.token, automation.id);
			if (selected?.id === automation.id) selected = null;
			await refresh();
		} catch (error) {
			toast.error(`${error}`);
		}
	};

	onMount(async () => {
		await refresh();
		const from = $page.url.searchParams.get('from');
		if (from) {
			await prefillFromChat(from);
		}
	});
</script>

<svelte:head>
	<title>{$i18n.t('Automations')} | {$WEBUI_NAME}</title>
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
				<div class="text-lg font-medium px-1.5">{$i18n.t('Automations')}</div>
			</div>
			<button
				class="mr-2 rounded-lg bg-gray-900 dark:bg-white text-white dark:text-gray-900 px-3 py-1.5 text-sm"
				on:click={() => {
					if (showForm && !editingId) {
						closeForm();
						return;
					}
					editingId = null;
					form = emptyForm();
					showForm = true;
				}}
			>
				{$i18n.t('New automation')}
			</button>
		</div>
	</nav>

	<div class="flex-1 overflow-y-auto px-4 py-4 max-w-4xl w-full mx-auto flex flex-col gap-4">
		{#if showForm}
			<form
				class="rounded-xl border border-gray-100 dark:border-gray-850 p-4 flex flex-col gap-2"
				on:submit|preventDefault={submit}
			>
				<div class="text-sm font-medium">
					{editingId ? $i18n.t('Edit automation') : $i18n.t('New automation')}
				</div>
				<input
					class="rounded-lg bg-gray-50 dark:bg-gray-850 px-3 py-2 text-sm outline-hidden"
					placeholder={$i18n.t('Name')}
					bind:value={form.name}
					required
				/>
				<textarea
					class="rounded-lg bg-gray-50 dark:bg-gray-850 px-3 py-2 text-sm outline-hidden"
					rows="4"
					placeholder={$i18n.t('Prompt to run')}
					bind:value={form.prompt}
					required
				/>
				<input
					class="rounded-lg bg-gray-50 dark:bg-gray-850 px-3 py-2 text-sm outline-hidden"
					placeholder={$i18n.t('Schedule (every day at noon, or 0 12 * * *)')}
					bind:value={form.cron}
				/>
				<select class="rounded-lg bg-gray-50 dark:bg-gray-850 px-3 py-2 text-sm" bind:value={form.model}>
					<option value="">{$i18n.t('Default model')}</option>
					{#each $models as model}
						<option value={model.id}>{model.name ?? model.id}</option>
					{/each}
				</select>
				<select class="rounded-lg bg-gray-50 dark:bg-gray-850 px-3 py-2 text-sm" bind:value={form.team_id}>
					<option value="">{$i18n.t('Personal')}</option>
					{#each $teams as team}
						<option value={team.id}>{team.name}</option>
					{/each}
				</select>
				<div class="flex items-center gap-2">
					<button
						class="rounded-lg bg-gray-900 dark:bg-white text-white dark:text-gray-900 px-3 py-1.5 text-sm"
						type="submit">{editingId ? $i18n.t('Save') : $i18n.t('Create')}</button
					>
					<button class="text-xs text-gray-400" type="button" on:click={closeForm}
						>{$i18n.t('Cancel')}</button
					>
				</div>
				{#if form.tool_ids?.length}
					<div class="text-xs text-gray-500">
						{$i18n.t('Will run with')}
						{form.tool_ids.length}
						{$i18n.t('enabled tools/skills from the source chat.')}
					</div>
				{/if}
			</form>
		{/if}

		{#if automations.length === 0 && !showForm}
			<div class="text-sm text-gray-500 text-center py-8">
				{$i18n.t('No automations yet. Create one, or ask in a chat to run a task on a schedule.')}
			</div>
		{/if}

		{#each sections as section}
			<section class="flex flex-col gap-2">
				<div class="text-xs font-medium text-gray-500 uppercase tracking-wide">{section.title}</div>
				{#each section.items as automation}
					<div class="rounded-xl border border-gray-100 dark:border-gray-850 p-4">
						<div class="flex items-start justify-between gap-3">
							<button class="text-left" on:click={() => openRuns(automation)}>
								<div class="font-medium">{automation.name}</div>
								<div class="text-xs text-gray-500">
									{automation.cron || $i18n.t('Manual')}
									· {automation.enabled ? $i18n.t('On') : $i18n.t('Off')}
								</div>
								<div class="text-xs text-gray-500 mt-1 line-clamp-2">{automation.prompt}</div>
							</button>
							<div class="flex gap-2 text-xs shrink-0">
								{#if canManage(automation)}
									<button class="text-gray-500" on:click={() => openEdit(automation)}
										>{$i18n.t('Edit')}</button
									>
									<button class="text-gray-500" on:click={() => toggle(automation)}
										>{automation.enabled ? $i18n.t('Disable') : $i18n.t('Enable')}</button
									>
								{/if}
								<button class="text-gray-900 dark:text-white" on:click={() => runNow(automation)}
									>{$i18n.t('Run now')}</button
								>
								{#if canManage(automation)}
									<button class="text-red-500" on:click={() => remove(automation)}
										>{$i18n.t('Delete')}</button
									>
								{/if}
							</div>
						</div>
						{#if selected?.id === automation.id}
							<div class="mt-3 flex flex-col gap-1">
								<div class="text-xs font-medium text-gray-500">{$i18n.t('Runs')}</div>
								{#each runs as run}
									<button
										class="text-left text-xs px-2 py-1 rounded hover:bg-gray-50 dark:hover:bg-gray-850 flex justify-between"
										on:click={() => run.chat_id && goto(`/c/${run.chat_id}`)}
									>
										<span>
											{run.status}
											{#if run.chat_title}
												· {run.chat_title}
											{/if}
											{#if run.error}
												· {run.error}
											{/if}
										</span>
										<span class="text-gray-400">
											{run.started_at ? new Date(run.started_at * 1000).toLocaleString() : ''}
										</span>
									</button>
								{:else}
									<div class="text-xs text-gray-400">{$i18n.t('No runs yet')}</div>
								{/each}
							</div>
						{/if}
					</div>
				{/each}
			</section>
		{/each}
	</div>
</div>
