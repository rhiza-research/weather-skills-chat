<script lang="ts">
	import { getContext } from 'svelte';
	import Collapsible from '../common/Collapsible.svelte';
	import ProvenanceTree from './ProvenanceTree.svelte';

	const i18n = getContext('i18n');

	export let steps: Array<any> = [];

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
</script>

{#each steps as step, stepIdx}
	<Collapsible
		title="{stepIdx + 1}. {step.skill}{step.version ? ` · ${step.version}` : ''}"
		open={false}
		chevron={true}
		buttonClassName="w-full text-xs text-body hover:text-gray-800 dark:hover:text-gray-200 transition"
		className="w-full"
	>
		<div class="mb-1.5 ml-1 space-y-1.5" slot="content">
			{#if argEntries(step.args).length}
				<div>
					<div class="text-xs font-medium text-muted mb-0.5">
						{$i18n.t('Arguments')}
					</div>
					<dl class="space-y-0.5">
						{#each argEntries(step.args) as [key, value]}
							<div class="grid grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)] gap-x-2 text-xs">
								<dt class="truncate text-muted" title={key}>
									{key}
								</dt>
								<dd
									class="m-0 whitespace-pre-wrap break-words text-body font-mono"
								>
									{formatArgValue(value)}
								</dd>
							</div>
						{/each}
					</dl>
				</div>
			{:else}
				<div class="text-xs text-subtle">{$i18n.t('No arguments.')}</div>
			{/if}

			{#if inputList(step.input).length}
				<div>
					<div class="text-xs font-medium text-muted mb-0.5">
						{$i18n.t('Inputs')}
					</div>
					<ul class="space-y-1">
						{#each inputList(step.input) as inp}
							<li class="text-xs text-body">
								<span class="font-mono break-all">{inp?.basename || '—'}</span>
								{#if inp?.history?.length}
									<div class="mt-0.5 pl-2 border-l border-line-strong">
										<ProvenanceTree
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
