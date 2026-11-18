<script lang="ts">
	import { getContext } from 'svelte';
	import { DropdownMenu } from 'bits-ui';
	import Dropdown from '$lib/components/common/Dropdown.svelte';
	import { flyAndScale } from '$lib/utils/transitions';

	const i18n = getContext('i18n');

	export let history;

	// The latest reply in this branch whose usage says how full the context was.
	$: usage = (() => {
		for (let m = history?.messages?.[history?.currentId]; m; m = history.messages[m.parentId]) {
			if (m.usage?.context_window) return m.usage;
		}
		return null;
	})();
	$: percent = usage ? Math.min(100, (usage.context_used / usage.context_window) * 100) : 0;
</script>

{#if usage}
	<Dropdown>
		<!-- r = 100/2π so the circumference is 100 and the dash length is the percent -->
		<svg
			viewBox="0 0 36 36"
			class="block size-[19.2px] -rotate-90 mr-3"
			role="img"
			aria-label={$i18n.t('Context usage')}
		>
			<circle
				cx="18"
				cy="18"
				r="15.9155"
				fill="none"
				stroke-width="4"
				class="stroke-gray-200 dark:stroke-gray-700"
			/>
			<circle
				cx="18"
				cy="18"
				r="15.9155"
				fill="none"
				stroke-width="4"
				stroke-dasharray="{percent} 100"
				class="stroke-gray-600 dark:stroke-gray-300"
			/>
		</svg>

		<div slot="content">
			<DropdownMenu.Content
				class="rounded-xl px-3 py-2 border border-gray-300/30 dark:border-gray-700/50 z-50 bg-white dark:bg-gray-850 dark:text-white shadow-sm text-sm"
				sideOffset={10}
				side="bottom"
				align="end"
				transition={flyAndScale}
			>
				<div class="font-medium">{$i18n.t('Context usage')}</div>
				<div class="mt-1 tabular-nums">
					{$i18n.t('{{used}} of {{total}} tokens', {
						used: usage.context_used.toLocaleString(),
						total: usage.context_window.toLocaleString()
					})}
				</div>
				<div class="text-gray-500 dark:text-gray-400 tabular-nums">
					{$i18n.t('{{percent}}% used', { percent: percent.toFixed(1) })}
				</div>
			</DropdownMenu.Content>
		</div>
	</Dropdown>
{/if}
