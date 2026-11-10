<script lang="ts">
	import { getContext } from 'svelte';
	import Collapsible from './Collapsible.svelte';
	import { toolUsageLine } from '$lib/chat/toolUsage';
	import type { ToolArgRow } from '$lib/chat/toolArgs';

	const i18n = getContext('i18n');

	export let head = '';
	export let args: ToolArgRow[] = [];
	export let pythonCode = '';
	export let blockId = 'tool-call';
	export let done = false;
	export let result: any = null;
	export let failed = false;
	export let secretNames: string[] = [];

	function outputText(result: any): string {
		if (!result) return '';
		if (result.kind === 'structured') {
			return [result.stdout, result.stderr, result.extra?.result]
				.filter((part) => part !== undefined && part !== null && part !== '')
				.join('\n\n')
				.trim();
		}
		if (result.kind === 'json' || result.kind === 'text') {
			return (result.text || '').trim();
		}
		return '';
	}

	$: text = outputText(result);
	$: usageLine = result?.kind === 'structured' ? toolUsageLine(result.extra?.tool_resource_usage) : '';

	let CodeBlockComponent = null;
	const loadCodeBlock = async () => {
		if (CodeBlockComponent) {
			return;
		}
		CodeBlockComponent = (await import('$lib/components/chat/Messages/CodeBlock.svelte')).default;
	};
	// Values longer than this start collapsed behind the code block's Expand button.
	const COLLAPSE_LINES = 20;

	$: if (pythonCode || args.some((arg) => arg.multiline)) {
		loadCodeBlock();
	}
</script>

<div class="space-y-1.5">
	{#if pythonCode && CodeBlockComponent}
		<svelte:component
			this={CodeBlockComponent}
			id={`${blockId}-python`}
			lang="python"
			code={pythonCode}
			run={false}
			collapsed={false}
			token={{ text: pythonCode, raw: `\`\`\`python\n${pythonCode}\n\`\`\`` }}
			className="my-1"
		/>
		{#if secretNames.length}
			<div class="text-xs text-gray-500 dark:text-gray-400">
				<span class="font-medium">{$i18n.t('Environment secrets')}:</span>
				{#each secretNames as name, idx}
					<code class="font-mono text-gray-700 dark:text-gray-200">{name}</code
					>{idx < secretNames.length - 1 ? ', ' : ''}
				{/each}
			</div>
		{/if}
	{:else}
		<Collapsible
			title={$i18n.t('Call')}
			open={false}
			buttonClassName="w-full text-xs text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 transition"
			className="w-full"
		>
			<div class="mb-1 space-y-1.5" slot="content">
				<p class="m-0 break-words font-sans text-sm leading-relaxed text-gray-700 dark:text-gray-200">
					{head}
				</p>
				{#if args.length}
					<!-- not-prose: the chat's prose styles give dt/dd large top margins. -->
					<dl class="not-prose m-0 space-y-0.5 text-sm text-gray-700 dark:text-gray-200">
						{#each args as arg, idx}
							<div class={arg.multiline ? '' : 'flex items-baseline gap-x-2'}>
								{#if arg.key}
									<dt class="shrink-0 font-mono text-xs font-semibold text-gray-900 dark:text-gray-100">
										{arg.key}
									</dt>
								{/if}
								<dd class="m-0 min-w-0 flex-1">
									{#if arg.multiline && CodeBlockComponent}
										<svelte:component
											this={CodeBlockComponent}
											id={`${blockId}-arg-${idx}`}
											lang={arg.lang}
											code={arg.value}
											run={false}
											collapsed={arg.value.split('\n').length > COLLAPSE_LINES}
											token={{ text: arg.value, raw: arg.value }}
											className="my-1"
										/>
									{:else}
										<span class="whitespace-pre-wrap break-words font-mono text-xs text-gray-600 dark:text-gray-300">{arg.value}</span>
									{/if}
								</dd>
							</div>
						{/each}
					</dl>
				{/if}
				{#if secretNames.length}
					<div class="text-xs text-gray-500 dark:text-gray-400">
						<span class="font-medium">{$i18n.t('Environment secrets')}:</span>
						{#each secretNames as name, idx}
							<code class="font-mono text-gray-700 dark:text-gray-200">{name}</code
							>{idx < secretNames.length - 1 ? ', ' : ''}
						{/each}
					</div>
				{/if}
			</div>
		</Collapsible>
	{/if}

	{#if done}
		<Collapsible
			title={$i18n.t('Output')}
			open={false}
			buttonClassName="w-full text-xs text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 transition"
			className="w-full"
		>
			<div class="mb-1" slot="content">
				{#if text}
					<pre
						class="m-0 whitespace-pre-wrap break-words font-sans text-sm leading-relaxed {failed
							? 'text-red-700 dark:text-red-300'
							: 'text-gray-700 dark:text-gray-200'}">{text}</pre>
				{:else}
					<p class="m-0 text-sm text-gray-500 dark:text-gray-400">
						{$i18n.t('No output.')}
					</p>
				{/if}
				{#if usageLine}
					<p class="m-0 mt-1.5 font-sans text-xs text-gray-500 dark:text-gray-400">{usageLine}</p>
				{/if}
			</div>
		</Collapsible>
	{/if}
</div>
