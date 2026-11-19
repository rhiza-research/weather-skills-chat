<script lang="ts">
	import XMarkSolid from '$lib/components/icons/XMarkSolid.svelte';
	import { getContext, tick } from 'svelte';
	import { toolServers, tools, WEBUI_NAME } from '$lib/stores';

	import { getToolSummary } from '$lib/apis/tools';
	import {
		dedupeToolsForSelection,
		isSkillDefaultEnabled,
		isSkillTool,
		remapSelectedToolIdsToHighestSkills,
		sortToolsByName,
		toolBaseName,
		toolSkillRepoRef,
		toolSkillVersion
	} from '$lib/utils/toolDisplay';

	import Modal from '../common/Modal.svelte';
	import Collapsible from '../common/Collapsible.svelte';
	import Switch from '../common/Switch.svelte';
	import ChevronDown from '../icons/ChevronDown.svelte';
	import ChevronUp from '../icons/ChevronUp.svelte';

	export let show = false;
	export let selectedToolIds: string[] = [];
	/** Feature flags for built-in tools; a group is on unless its flag is false. */
	export let builtinFeatures: Record<string, boolean> = {};
	/** Which built-in groups to offer switches for. */
	export let builtinGroups: string[] = [];

	const i18n = getContext('i18n');

	let query = '';
	let searchEl: HTMLInputElement | null = null;
	let expanded: Record<string, boolean> = {};
	let opened = false;

	$: visibleTools = sortToolsByName(dedupeToolsForSelection($tools ?? []));

	$: q = query.trim().toLowerCase();
	$: filteredTools = q
		? visibleTools.filter((tool) => toolBaseName(tool).toLowerCase().includes(q))
		: visibleTools;
	$: filteredToolServers = q
		? $toolServers.filter((server) =>
				(server?.openapi?.info?.title ?? '').toLowerCase().includes(q)
			)
		: $toolServers;

	const onOpen = async () => {
		query = '';
		expanded = {};
		if ($tools === null) {
			tools.set(await getToolSummary(localStorage.token));
		}
		selectedToolIds = remapSelectedToolIdsToHighestSkills(selectedToolIds ?? [], $tools ?? []);
		await tick();
		searchEl?.focus();
	};

	$: if (show && !opened) {
		opened = true;
		void onOpen();
	} else if (!show && opened) {
		opened = false;
	}

	$: builtinOptions = [
		{
			key: 'email',
			name: $i18n.t('Email'),
			description: $i18n.t('Send email, with files from the chat attached.')
		},
		{
			key: 'scheduled_tasks',
			name: $i18n.t('Scheduled tasks'),
			description: $i18n.t('Create, list, change, and delete scheduled tasks.')
		},
		{
			key: 'preferences',
			name: $i18n.t('Preferences'),
			description: $i18n.t('Read and save preferences for this organization.')
		}
	].filter((option) => builtinGroups.includes(option.key));

	const setBuiltinEnabled = (key: string, enabled: boolean) => {
		if (enabled === (builtinFeatures?.[key] !== false)) return;
		builtinFeatures = { ...(builtinFeatures ?? {}), [key]: enabled };
	};

	// Switch dispatches its state on mount too, so only write when it changes.
	const setToolEnabled = (toolId: string, enabled: boolean) => {
		if (enabled === selectedToolIds.includes(toolId)) return;
		selectedToolIds = enabled
			? [...selectedToolIds, toolId]
			: selectedToolIds.filter((id) => id !== toolId);
	};
</script>

<Modal bind:show size="md">
	<div>
		<div class=" flex justify-between dark:text-gray-300 px-5 pt-4 pb-0.5">
			<h2 class="text-lg font-medium self-center">{$i18n.t('Available Tools and Skills')}</h2>
			<button
				class="self-center"
				aria-label={$i18n.t('Close')}
				on:click={() => {
					show = false;
				}}
			>
				<XMarkSolid className="size-5" />
			</button>
		</div>

		<div class="px-5 pt-2 pb-2">
			<input
				bind:this={searchEl}
				bind:value={query}
				type="search"
				placeholder={$i18n.t('Search tools')}
				class="field border border-transparent focus:border-gray-200 dark:focus:border-gray-700"
			/>
		</div>

		{#if builtinOptions.length > 0}
			<div class=" flex justify-between dark:text-gray-300 px-5 pb-1">
				<h3 class="text-base font-medium self-center">{$i18n.t('Built-in Tools')}</h3>
			</div>
			<div class="px-3 pb-2 w-full flex flex-col">
				{#each builtinOptions as option (option.key)}
					<div
						class="px-2 py-1.5 rounded-xl hover:bg-tint transition flex items-center gap-2"
					>
						<div class="flex-1 min-w-0">
							<div class="text-sm font-medium text-strong">
								{option.name}
							</div>
							<div class="text-xs text-muted">{option.description}</div>
						</div>
						<div class="shrink-0">
							<Switch
								state={builtinFeatures?.[option.key] !== false}
								on:change={(e) => setBuiltinEnabled(option.key, e.detail)}
							/>
						</div>
					</div>
				{/each}
			</div>
		{/if}

		{#if visibleTools.length > 0}
			{#if builtinOptions.length > 0 || $toolServers.length > 0}
				<div class=" flex justify-between dark:text-gray-300 px-5 pb-1">
					<h3 class="text-base font-medium self-center">{$i18n.t('Weather Skills')}</h3>
				</div>
			{/if}

			<div class="px-3 pb-3 w-full flex flex-col max-h-[60vh] overflow-y-auto">
				{#each filteredTools as tool (tool.id)}
					{@const version = toolSkillVersion(tool)}
					{@const repoRef = toolSkillRepoRef(tool)}
					{@const description = tool?.meta?.description}
					<div class="px-2 py-1.5 rounded-xl hover:bg-tint transition">
						<div class="flex items-center gap-2">
							<button
								type="button"
								class="flex-1 min-w-0 flex items-center gap-1.5 text-left {description
									? 'cursor-pointer'
									: 'cursor-default'}"
								aria-expanded={description ? !!expanded[tool.id] : undefined}
								on:click={() => {
									if (description) {
										expanded = { ...expanded, [tool.id]: !expanded[tool.id] };
									}
								}}
							>
								<div class="min-w-0">
									<div
										class="text-sm font-medium text-strong flex flex-wrap items-center gap-1.5"
									>
										<span class="truncate">{toolBaseName(tool)}</span>
										{#if isSkillTool(tool) && version}
											<span
												class="text-xs font-semibold px-1 rounded-sm bg-gray-500/15 text-body"
											>
												v{version}
											</span>
										{/if}
										{#if isSkillTool(tool) && repoRef}
											<span
												class="text-xs font-mono font-semibold px-1 rounded-sm bg-gray-500/15 text-body"
											>
												{repoRef}
											</span>
										{/if}
										{#if !isSkillDefaultEnabled(tool)}
											<span class="text-xs text-muted">
												{$i18n.t('off by default')}
											</span>
										{/if}
									</div>
								</div>

								{#if description}
									<div class="shrink-0 text-muted">
										{#if expanded[tool.id]}
											<ChevronUp strokeWidth="2.5" className="size-3" />
										{:else}
											<ChevronDown strokeWidth="2.5" className="size-3" />
										{/if}
									</div>
								{/if}
							</button>

							<div class="shrink-0">
								<Switch
									state={selectedToolIds.includes(tool.id)}
									on:change={(e) => setToolEnabled(tool.id, e.detail)}
								/>
							</div>
						</div>

						{#if description && expanded[tool.id]}
							<div class="mt-1 text-xs text-muted whitespace-pre-line">
								{description}
							</div>
						{/if}
					</div>
				{/each}

				{#if filteredTools.length === 0}
					<div class="px-2 py-2 text-xs text-muted">
						{$i18n.t('No skills match your search')}
					</div>
				{/if}
			</div>
		{/if}

		{#if $toolServers.length > 0}
			<div class=" flex justify-between dark:text-gray-300 px-5 pb-0.5">
				<h3 class="text-base font-medium self-center">{$i18n.t('Tool Servers')}</h3>
			</div>

			<div class="px-5 pb-5 w-full flex flex-col justify-center">
				<div class="text-xs text-body mb-2">
					{$i18n.t('{{WEBUI_NAME}} can use tools provided by any OpenAPI server.', {
						WEBUI_NAME: $WEBUI_NAME
					})}
				</div>
				<div class=" text-sm dark:text-gray-300 mb-1">
					{#each filteredToolServers as toolServer}
						<Collapsible buttonClassName="w-full" chevron>
							<div class="text-sm font-medium text-strong">
								{toolServer?.openapi?.info?.title} - v{toolServer?.openapi?.info?.version}
							</div>

							<div slot="content">
								<div class="text-xs text-muted">
									{toolServer?.openapi?.info?.description}
								</div>

								<div class="text-xs text-muted">
									{toolServer?.url}
								</div>

								{#each toolServer?.specs ?? [] as tool_spec}
									<div class="my-1">
										<div class="font-medium text-strong">
											{tool_spec?.name}
										</div>

										<div>
											{tool_spec?.description}
										</div>
									</div>
								{/each}
							</div>
						</Collapsible>
					{/each}
				</div>
			</div>
		{/if}
	</div>
</Modal>
