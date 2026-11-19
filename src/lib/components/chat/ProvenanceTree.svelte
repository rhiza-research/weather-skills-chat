<script lang="ts">
	import { getContext } from 'svelte';
	import Collapsible from '../common/Collapsible.svelte';
	import Spinner from '../common/Spinner.svelte';
	import ChevronDown from '../icons/ChevronDown.svelte';
	import ChevronRight from '../icons/ChevronRight.svelte';
	import ProvenanceSteps from './ProvenanceSteps.svelte';

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
					buttonClassName="w-full min-w-0 text-xs leading-snug text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 transition"
					className="w-full min-w-0"
					on:change={(e) => {
						opened[branchIdx] = e.detail;
						e.detail && failed && load();
					}}
				>
					{#if opened[branchIdx]}
						<ChevronDown className="size-3 shrink-0 self-center mr-1 text-gray-400" />
					{:else}
						<ChevronRight className="size-3 shrink-0 self-center mr-1 text-gray-400" />
					{/if}
					<span class="min-w-0 flex-1 truncate text-left" title={branchTitle}>{branchTitle}</span>
					{#if pressed === branchIdx}
						<div class="shrink-0 self-start translate-y-0.5 mx-1">
							<Spinner className="size-3" />
						</div>
					{/if}
					<div class="mb-1 pl-1 space-y-1" slot="content">
						{#if !branch?.steps && loadSteps && failed}
							<div class="text-xs text-gray-400">{$i18n.t('Could not load provenance.')}</div>
						{:else if steps.length === 0}
							<div class="text-xs text-gray-400">{$i18n.t('No steps recorded.')}</div>
						{:else}
							<ProvenanceSteps {steps} />
						{/if}
					</div>
				</Collapsible>
			</div>
		{/each}
	</div>
{/if}
