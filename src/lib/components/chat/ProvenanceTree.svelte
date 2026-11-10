<script lang="ts">
	import { getContext } from 'svelte';
	import Collapsible from '../common/Collapsible.svelte';
	import Spinner from '../common/Spinner.svelte';

	const i18n = getContext('i18n');

	export let branches: Array<{
		label?: string | null;
		steps?: Array<any>;
		crumbs?: string[];
	}> = [];
	// When branches arrive without steps (artifact listings carry only names),
	// the first branch opened calls this for the full branches, in the same order.
	export let loadSteps: (() => Promise<Array<{ steps?: Array<any> }> | null>) | null = null;

	let loaded: Array<{ steps?: Array<any> }> | null = null;
	let loading = false;
	let failed = false;
	// Branches opened once their steps loaded.
	let opened: Record<number, boolean> = {};
	// The branch whose press is waiting on its steps; its row shows a spinner.
	let pressed: number | null = null;

	const load = async () => {
		if (!loadSteps || loading) return;
		loading = true;
		try {
			loaded = (await loadSteps()) ?? [];
			failed = false;
		} catch (e) {
			console.error(e);
			failed = true;
		} finally {
			loading = false;
		}
	};

	// A press on a branch whose steps are not here yet keeps it closed until they
	// load, then opens it: the slide measures its content when it starts, so
	// opening first would show one line until the slide ended. Collapsible
	// toggles on pointerup, so that is the event held back.
	const onBranchPress = async (event: PointerEvent, branchIdx: number, branch) => {
		if (branch?.steps || !loadSteps || loaded || failed) return;
		event.stopPropagation();
		event.preventDefault();
		if (loading) return;
		pressed = branchIdx;
		await load();
		pressed = null;
		opened = { ...opened, [branchIdx]: true };
	};

	const formatArgValue = (value: any): string => {
		if (value === null || value === undefined) return 'null';
		if (typeof value === 'string') {
			if (value === '') return '""';
			return value;
		}
		if (typeof value === 'number' || typeof value === 'boolean') {
			return String(value);
		}
		try {
			return JSON.stringify(value, null, 2);
		} catch {
			return String(value);
		}
	};

	const argEntries = (args: any): Array<[string, any]> => {
		if (!args || typeof args !== 'object' || Array.isArray(args)) return [];
		return Object.entries(args);
	};

	const inputList = (input: any): any[] => {
		if (!input) return [];
		return Array.isArray(input) ? input : [input];
	};

	const crumbLabel = (
		branch: (typeof branches)[number],
		branchIdx: number,
		total: number
	): string => {
		const crumbs =
			Array.isArray(branch?.crumbs) && branch.crumbs.length
				? branch.crumbs
				: (branch?.steps || []).map((s) => s?.skill).filter(Boolean);
		const trail = crumbs.join(' → ') || $i18n.t('Provenance');
		if (total > 1) {
			return `${$i18n.t('Branch {{n}}', { n: branchIdx + 1 })}: ${trail}`;
		}
		return trail;
	};
</script>

{#if branches?.length}
	<div class="mt-0.5 space-y-1">
		{#each branches as branch, branchIdx}
			{@const steps = branch?.steps || loaded?.[branchIdx]?.steps || []}
			{@const branchTitle = crumbLabel(branch, branchIdx, branches.length)}
			<!-- svelte-ignore a11y-click-events-have-key-events a11y-no-static-element-interactions -->
			<div on:pointerup|capture={(e) => onBranchPress(e, branchIdx, branch)}>
				<Collapsible
					title={null}
					open={opened[branchIdx] ?? false}
					chevron={true}
					buttonClassName="w-full min-w-0 text-[10px] leading-snug text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 transition"
					className="w-full min-w-0"
					on:change={(e) => e.detail && failed && load()}
				>
					<span class="min-w-0 flex-1 truncate text-left" title={branchTitle}>{branchTitle}</span>
					{#if pressed === branchIdx}
						<div class="shrink-0 self-start translate-y-0.5 mx-1">
							<Spinner className="size-3" />
						</div>
					{/if}
					<div class="mb-1 pl-1 space-y-1" slot="content">
						{#if !branch?.steps && loadSteps && failed}
							<div class="text-[10px] text-gray-400">{$i18n.t('Could not load provenance.')}</div>
						{:else if steps.length === 0}
							<div class="text-[10px] text-gray-400">{$i18n.t('No steps recorded.')}</div>
						{:else}
							{#each steps as step, stepIdx}
								<Collapsible
									title="{stepIdx + 1}. {step.skill}{step.version ? ` · ${step.version}` : ''}"
									open={false}
									chevron={true}
									buttonClassName="w-full text-[10px] text-gray-600 hover:text-gray-800 dark:text-gray-400 dark:hover:text-gray-200 transition"
									className="w-full"
								>
									<div class="mb-1.5 ml-1 space-y-1.5" slot="content">
										{#if argEntries(step.args).length}
											<div>
												<div class="text-[10px] font-medium text-gray-500 dark:text-gray-400 mb-0.5">
													{$i18n.t('Arguments')}
												</div>
												<dl class="space-y-0.5">
													{#each argEntries(step.args) as [key, value]}
														<div class="grid grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)] gap-x-2 text-[10px]">
															<dt class="truncate text-gray-500 dark:text-gray-400" title={key}>
																{key}
															</dt>
															<dd
																class="m-0 whitespace-pre-wrap break-words text-gray-700 dark:text-gray-200 font-mono"
															>
																{formatArgValue(value)}
															</dd>
														</div>
													{/each}
												</dl>
											</div>
										{:else}
											<div class="text-[10px] text-gray-400">{$i18n.t('No arguments.')}</div>
										{/if}

										{#if inputList(step.input).length}
											<div>
												<div class="text-[10px] font-medium text-gray-500 dark:text-gray-400 mb-0.5">
													{$i18n.t('Inputs')}
												</div>
												<ul class="space-y-1">
													{#each inputList(step.input) as inp}
														<li class="text-[10px] text-gray-700 dark:text-gray-200">
															<span class="font-mono break-all">{inp?.basename || '—'}</span>
															{#if inp?.history?.length}
																<div class="mt-0.5 pl-2 border-l border-gray-200 dark:border-gray-700">
																	<svelte:self
																		branches={[
																			{
																				label: inp.basename || null,
																				steps: inp.history,
																				crumbs: inp.history.map((s) => s?.skill).filter(Boolean)
																			}
																		]}
																	/>
																</div>
															{/if}
														</li>
													{/each}
												</ul>
											</div>
										{/if}
									</div>
								</Collapsible>
							{/each}
						{/if}
					</div>
				</Collapsible>
			</div>
		{/each}
	</div>
{/if}
