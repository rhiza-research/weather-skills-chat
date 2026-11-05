<script lang="ts">
	import { getContext } from 'svelte';
	import Collapsible from '../common/Collapsible.svelte';
	import Spinner from '../common/Spinner.svelte';
	import ProvenanceTree from './ProvenanceTree.svelte';
	import { getArtifactProvenance } from '$lib/apis/artifacts';
	import { chatId } from '$lib/stores';

	const i18n = getContext('i18n');

	export let file: { path: string; provenance?: string[]; modified?: number | null };

	// The listing carries only crumbs; the branches load when the row is opened.
	let open = false;
	let branches: any[] | null = null;
	let loadedKey = '';
	let failed = false;

	$: label = (file?.provenance ?? []).join(' → ');
	$: key = `${$chatId}:${file?.path}:${file?.modified ?? ''}`;
	$: if (open && key !== loadedKey) load(key);

	const load = async (requested: string) => {
		loadedKey = requested;
		branches = null;
		failed = false;
		try {
			const detail = await getArtifactProvenance(localStorage.token, $chatId, file.path);
			if (requested === loadedKey) branches = detail?.branches ?? [];
		} catch (e) {
			console.error(e);
			if (requested === loadedKey) failed = true;
		}
	};
</script>

{#if label}
	<Collapsible
		title={null}
		bind:open
		chevron={true}
		buttonClassName="w-full min-w-0 text-[10px] leading-snug text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-300 transition"
		className="w-full min-w-0"
	>
		<span class="min-w-0 flex-1 truncate text-left" title={label}>{label}</span>
		<div class="pl-1" slot="content">
			{#if failed}
				<div class="text-[10px] text-gray-400">{$i18n.t('Could not load provenance.')}</div>
			{:else if branches === null}
				<Spinner className="size-3" />
			{:else if branches.length}
				<ProvenanceTree {branches} />
			{:else}
				<div class="text-[10px] text-gray-400">{$i18n.t('No steps recorded.')}</div>
			{/if}
		</div>
	</Collapsible>
{/if}
