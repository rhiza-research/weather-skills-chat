<script lang="ts">
	import { getContext, createEventDispatcher } from 'svelte';
	import ProvenanceTree from './ProvenanceTree.svelte';
	import ChevronDown from '../icons/ChevronDown.svelte';
	import ChevronRight from '../icons/ChevronRight.svelte';
	import { getArtifactArchiveUrl, getArtifactContentUrl } from '$lib/apis/artifacts';
	import { chatId } from '$lib/stores';
	import { htmlHasFigureJson } from '$lib/chat/artifactsList';

	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher();

	export let node: {
		name: string;
		path: string;
		file: any | null;
		children: any[];
	};
	export let depth = 0;
	export let files: any[] = [];
	export let expanded: Set<string> = new Set();
	export let selectedImage: string | null = null;

	const isNavigableDir = (n) => {
		const kind = n.file?.kind;
		if (kind === 'zarr') return false;
		if (kind === 'directory' || n.file?.is_dir) return true;
		return n.children?.length > 0 && !n.file;
	};

	const provenanceLabel = (file) => {
		const crumbs = file?.provenance_detail?.crumbs ?? file?.provenance;
		if (!Array.isArray(crumbs) || crumbs.length === 0) return '';
		return crumbs.join(' → ');
	};

	const provenanceBranches = (file) => {
		const branches = file?.provenance_detail?.branches;
		return Array.isArray(branches) ? branches : [];
	};

	const kindLabel = (file) => {
		if (!file) return 'folder';
		return file.kind || (file.is_dir ? 'folder' : 'file');
	};

	const toggle = () => {
		dispatch('toggle', { path: node.path });
	};

	const downloadFile = async (path: string, name: string) => {
		try {
			const res = await fetch(getArtifactContentUrl($chatId, path), {
				headers: { authorization: `Bearer ${localStorage.token}` }
			});
			if (!res.ok) throw new Error(`download failed: ${res.status}`);
			const blob = await res.blob();
			const objectUrl = URL.createObjectURL(blob);
			const link = document.createElement('a');
			link.href = objectUrl;
			link.download = name || path.split('/').pop() || 'download';
			document.body.appendChild(link);
			link.click();
			document.body.removeChild(link);
			URL.revokeObjectURL(objectUrl);
		} catch (e) {
			console.error(e);
		}
	};

	$: file = node.file;
	$: navigable = isNavigableDir(node);
	$: open = expanded.has(node.path);
	$: pad = `padding-left: ${depth * 0.75 + 0.25}rem`;
	$: selected = (file?.kind === 'image' || file?.kind === 'html') && selectedImage === file.path;
</script>

{#if navigable}
	<div class="flex flex-col">
		<button
			type="button"
			class="flex items-center gap-1 w-full text-left text-xs px-1 py-1 rounded-md hover:bg-black/5 dark:hover:bg-white/5"
			style={pad}
			on:click={toggle}
		>
			{#if open}
				<ChevronDown className="size-3 shrink-0 text-gray-400" />
			{:else}
				<ChevronRight className="size-3 shrink-0 text-gray-400" />
			{/if}
			<span class="truncate min-w-0">{node.name}</span>
			<span class="text-gray-400 shrink-0">{kindLabel(file)}</span>
		</button>
		{#if open}
			{#each node.children as child}
				<svelte:self
					node={child}
					depth={depth + 1}
					{expanded}
					{selectedImage}
					on:toggle
					on:openImage
					on:openFigure
				/>
			{/each}
		{/if}
	</div>
{:else if file?.kind === 'zarr'}
	<div class="flex flex-col gap-0.5">
		<div class="flex items-center justify-between gap-2 text-xs px-1 py-1 rounded-md" style={pad}>
			<div class="truncate flex items-center gap-1 min-w-0">
				<span class="truncate">{node.name}</span>
				<span class="text-gray-400 shrink-0">zarr</span>
			</div>
			<a
				class="underline shrink-0"
				href={getArtifactArchiveUrl($chatId, file.path)}
				target="_blank"
				rel="noreferrer">{$i18n.t('Download')}</a
			>
		</div>
		{#if provenanceBranches(file).length}
			<div style={`padding-left: ${(depth + 1) * 0.75 + 0.25}rem`}>
				<ProvenanceTree branches={provenanceBranches(file)} />
			</div>
		{:else if provenanceLabel(file)}
			<div
				class="text-[10px] leading-snug text-gray-500 dark:text-gray-400 truncate"
				style={`padding-left: ${(depth + 1) * 0.75 + 0.25}rem`}
				title={provenanceLabel(file)}
			>
				{provenanceLabel(file)}
			</div>
		{/if}
	</div>
{:else if file}
	<div
		class="flex flex-col gap-0.5 rounded-md {selected
			? 'bg-black/5 dark:bg-white/5'
			: 'hover:bg-black/5 dark:hover:bg-white/5'}"
	>
		<div class="flex items-center justify-between gap-2 text-xs px-1 py-1" style={pad}>
			{#if file.kind === 'image' || (file.kind === 'html' && !htmlHasFigureJson(file, files))}
				<button
					type="button"
					class="truncate flex items-center gap-1 text-left hover:underline min-w-0"
					on:click={() => dispatch('openImage', { path: file.path })}
				>
					<span class="truncate">{node.name}</span>
					<span class="text-gray-400 shrink-0">{file.kind}</span>
				</button>
			{:else}
				<div class="truncate flex items-center gap-1 min-w-0">
					<span class="truncate">{node.name}</span>
					<span class="text-gray-400 shrink-0">{kindLabel(file)}</span>
				</div>
			{/if}
			<div class="flex gap-1 shrink-0">
				{#if file.kind === 'image' || (file.kind === 'html' && !htmlHasFigureJson(file, files))}
					<button
						type="button"
						class="underline"
						on:click={() => dispatch('openImage', { path: file.path })}
					>
						{$i18n.t('Open')}
					</button>
					<button
						type="button"
						class="underline"
						on:click={() => downloadFile(file.path, node.name)}
					>
						{$i18n.t('Download')}
					</button>
				{:else if file.kind === 'zarr'}
					<button
						type="button"
						class="underline"
						on:click={() =>
							downloadFile(
								file.path,
								node.name.endsWith('.zip') ? node.name : `${node.name}.zip`
							)}
					>
						{$i18n.t('Download')}
					</button>
				{:else if !file.is_dir}
					{#if node.name.endsWith('.plotly.json')}
						<button
							type="button"
							class="underline"
							on:click={() => dispatch('openFigure', { path: file.path })}
						>
							{$i18n.t('Open')}
						</button>
					{/if}
					<a
						class="underline"
						href={getArtifactContentUrl($chatId, file.path)}
						download={node.name}
						target="_blank"
						rel="noreferrer">{$i18n.t('Download')}</a
					>
				{/if}
			</div>
		</div>
		{#if provenanceBranches(file).length}
			<div style={`padding-left: ${(depth + 1) * 0.75 + 0.25}rem`}>
				<ProvenanceTree branches={provenanceBranches(file)} />
			</div>
		{:else if provenanceLabel(file)}
			<div
				class="text-[10px] leading-snug text-gray-500 dark:text-gray-400 truncate"
				style={`padding-left: ${(depth + 1) * 0.75 + 0.25}rem`}
				title={provenanceLabel(file)}
			>
				{provenanceLabel(file)}
			</div>
		{/if}
	</div>
{/if}
