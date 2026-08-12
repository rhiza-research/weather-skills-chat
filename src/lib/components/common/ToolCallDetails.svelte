<script lang="ts">
	import { getContext } from 'svelte';
	import Collapsible from './Collapsible.svelte';

	const i18n = getContext('i18n');

	export let callSignature = '';
	export let done = false;
	export let result: any = null;
	export let failed = false;

	function outputText(result: any): string {
		if (!result) return '';
		if (result.kind === 'structured') {
			return [result.stdout, result.stderr].filter(Boolean).join('\n\n').trim();
		}
		if (result.kind === 'json' || result.kind === 'text') {
			return (result.text || '').trim();
		}
		return '';
	}

	$: text = outputText(result);
</script>

<div class="space-y-1.5">
	<Collapsible
		title={$i18n.t('Call')}
		open={false}
		buttonClassName="w-full text-xs text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 transition"
		className="w-full"
	>
		<div class="mb-1" slot="content">
			<p class="m-0 break-words font-sans text-sm leading-relaxed text-gray-700 dark:text-gray-200">
				{callSignature}
			</p>
		</div>
	</Collapsible>

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
			</div>
		</Collapsible>
	{/if}
</div>
