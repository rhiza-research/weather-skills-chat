<script lang="ts">
	import { getContext, onMount, tick } from 'svelte';
	import { getSecrets } from '$lib/apis/secrets';

	const i18n = getContext('i18n');

	export let prompt = '';
	export let query = '';

	let selectedIdx = 0;
	let secrets = [];

	$: filtered = secrets.filter(
		(secret) =>
			!secret.overridden && secret.name.toLowerCase().includes((query || '').toLowerCase())
	);

	$: if (query !== undefined) {
		selectedIdx = 0;
	}

	export const selectUp = () => {
		selectedIdx = Math.max(0, selectedIdx - 1);
	};

	export const selectDown = () => {
		selectedIdx = Math.min(selectedIdx + 1, filtered.length - 1);
	};

	export const select = () => {
		if (filtered[selectedIdx]) {
			confirm(filtered[selectedIdx]);
		}
	};

	const confirm = (secret) => {
		const placeholder = `{{secret:${secret.name}}}`;
		prompt = prompt.replace(/\{\{secret:?[A-Za-z0-9_]*$/, placeholder + ' ');
	};

	onMount(async () => {
		secrets = await getSecrets(localStorage.token).catch(() => []);
		await tick();
		document.getElementById('secret-item-0')?.scrollIntoView();
	});
</script>

{#if filtered.length}
	<div
		id="commands-container"
		class="px-2 mb-2 text-left w-full absolute bottom-0 left-0 right-0 z-10"
	>
		<div class="flex w-full rounded-xl border border-gray-100 dark:border-gray-850 overflow-hidden">
			<div class="max-h-60 flex flex-col w-full rounded-xl bg-white dark:bg-gray-900 dark:text-gray-100">
				{#each filtered as secret, idx}
					<button
						id="secret-item-{idx}"
						class="px-3 py-1.5 text-left text-sm hover:bg-gray-50 dark:hover:bg-gray-800 {idx ===
						selectedIdx
							? 'bg-gray-50 dark:bg-gray-800 selected-command-option-button'
							: ''}"
						on:click={() => confirm(secret)}
						on:mousemove={() => (selectedIdx = idx)}
					>
						<div class="font-mono">{secret.name}</div>
						<div class="text-[11px] text-gray-400">
							{#if !secret.team_id && secrets.some((s) => s.team_id && s.name === secret.name)}
								{$i18n.t('Personal · overrides team')}
							{:else}
								{secret.team_name || $i18n.t('Personal')}
							{/if}
						</div>
					</button>
				{/each}
			</div>
		</div>
	</div>
{/if}
