<script lang="ts">
	import Checkbox from '$lib/components/common/Checkbox.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import { getContext, onMount } from 'svelte';
	import {
		dedupeToolsForSelection,
		isSkillTool,
		remapSelectedToolIdsToHighestSkills,
		toolBaseName,
		toolSelectionLabel,
		toolSkillRepoRef,
		toolSkillVersion
	} from '$lib/utils/toolDisplay';

	export let tools = [];

	let _tools = {};

	export let selectedToolIds = [];

	const i18n = getContext('i18n');

	$: toolIds = Object.keys(_tools);
	$: selectedCount = toolIds.filter((id) => _tools[id]?.selected).length;
	$: allSelected = toolIds.length > 0 && selectedCount === toolIds.length;
	$: someSelected = selectedCount > 0 && !allSelected;
	$: selectAllState = allSelected ? 'checked' : someSelected ? 'indeterminate' : 'unchecked';

	const syncSelectedToolIds = () => {
		selectedToolIds = Object.keys(_tools).filter((t) => _tools[t].selected);
	};

	const setAllSelected = (selected: boolean) => {
		for (const id of Object.keys(_tools)) {
			_tools[id].selected = selected;
		}
		_tools = _tools;
		syncSelectedToolIds();
	};

	onMount(() => {
		const visibleTools = dedupeToolsForSelection(tools ?? []);
		selectedToolIds = remapSelectedToolIdsToHighestSkills(selectedToolIds ?? [], tools ?? []);

		_tools = visibleTools.reduce((acc, tool) => {
			acc[tool.id] = {
				...tool,
				selected: selectedToolIds.includes(tool.id)
			};

			return acc;
		}, {});
	});
</script>

<div>
	<div class="flex w-full justify-between mb-1">
		<div class=" self-center text-sm font-semibold">{$i18n.t('Tools')}</div>
	</div>

	<div class=" text-xs dark:text-gray-500">
		{$i18n.t('To select toolkits here, add them to the "Tools" workspace first.')}
	</div>

	<div class="flex flex-col">
		{#if toolIds.length > 0}
			<div class=" flex flex-col items-stretch mt-2 gap-1.5">
				<div class=" flex items-center gap-2 pb-1 mb-0.5 border-b border-gray-100 dark:border-gray-800">
					<div class="self-center flex items-center shrink-0">
						<Checkbox
							state={selectAllState === 'checked' ? 'checked' : 'unchecked'}
							indeterminate={selectAllState === 'indeterminate'}
							on:change={(e) => {
								setAllSelected(e.detail === 'checked');
							}}
						/>
					</div>
					<button
						type="button"
						class="py-0.5 text-sm font-medium text-left"
						on:click={() => setAllSelected(!allSelected)}
					>
						{allSelected ? $i18n.t('Deselect All') : $i18n.t('Select All')}
					</button>
				</div>

				{#each toolIds as tool}
					{@const item = _tools[tool]}
					{@const version = toolSkillVersion(item)}
					{@const repoRef = toolSkillRepoRef(item)}
					<div class=" flex items-start gap-2">
						<div class="self-center flex items-center shrink-0">
							<Checkbox
								state={item.selected ? 'checked' : 'unchecked'}
								on:change={(e) => {
									_tools[tool].selected = e.detail === 'checked';
									_tools = _tools;
									syncSelectedToolIds();
								}}
							/>
						</div>

						<Tooltip
							content={item?.meta?.description || toolSelectionLabel(item)}
							placement="top-start"
							className="min-w-0"
						>
							<div class="py-0.5 text-sm w-full font-medium min-w-0">
								<div class="flex flex-wrap items-center gap-1.5">
									{#if isSkillTool(item)}
										<span
											class="text-[10px] font-bold px-1 rounded-sm uppercase bg-amber-500/20 text-amber-800 dark:text-amber-200"
										>
											skill
										</span>
									{/if}
									<span class="break-all">{toolBaseName(item)}</span>
									{#if version}
										<span
											class="text-[10px] font-semibold px-1 rounded-sm bg-gray-500/15 text-gray-600 dark:text-gray-300"
										>
											v{version}
										</span>
									{/if}
									{#if repoRef}
										<span
											class="text-[10px] font-mono font-semibold px-1 rounded-sm bg-gray-500/15 text-gray-600 dark:text-gray-300"
										>
											{repoRef}
										</span>
									{/if}
								</div>
							</div>
						</Tooltip>
					</div>
				{/each}
			</div>
		{/if}
	</div>
</div>
