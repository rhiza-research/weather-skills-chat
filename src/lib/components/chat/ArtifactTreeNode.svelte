<script lang="ts" context="module">
	import { writable } from 'svelte/store';

	// Listings carry crumbs for top-level entries only; deeper ones get theirs when their
	// provenance is opened, kept by chat, path and modification time across list refreshes.
	export const openedCrumbs = writable<Record<string, string[]>>({});
	export const crumbsKey = (chatId: string, path: string, modified?: number | null) =>
		`${chatId}\n${path}\n${modified ?? ''}`;
</script>

<script lang="ts">
	import { getContext, createEventDispatcher } from 'svelte';
	import ProvenanceStamp from '../icons/ProvenanceStamp.svelte';
	import ChevronDown from '../icons/ChevronDown.svelte';
	import ChevronRight from '../icons/ChevronRight.svelte';
	import ArrowsPointingOut from '../icons/ArrowsPointingOut.svelte';
	import ArrowDownTray from '../icons/ArrowDownTray.svelte';
	import DocumentDuplicate from '../icons/DocumentDuplicate.svelte';
	import Tooltip from '../common/Tooltip.svelte';
	import ConfirmDialog from '../common/ConfirmDialog.svelte';
	import {
		getArtifactArchiveUrl,
		getArtifactContentUrl,
		getArtifactSize,
		getArtifactViewUrl
	} from '$lib/apis/artifacts';
	import { chatId, user } from '$lib/stores';
	import { copyToClipboard, formatFileSize } from '$lib/utils';
	import { toast } from 'svelte-sonner';

	const i18n = getContext('i18n');
	// The same look as the preview pane's icon buttons.
	const iconButton =
		'p-1 rounded-md text-gray-500 hover:text-gray-800 dark:hover:text-gray-200 hover:bg-black/5 dark:hover:bg-white/5';
	const dispatch = createEventDispatcher();

	export let node: {
		name: string;
		path: string;
		file: any | null;
		children: any[];
	};
	export let depth = 0;
	export let expanded: Set<string> = new Set();
	export let selectedImage: string | null = null;

	const isNavigableDir = (n) => {
		const kind = n.file?.kind;
		if (kind === 'zarr') return false;
		if (kind === 'directory' || n.file?.is_dir) return true;
		return n.children?.length > 0 && !n.file;
	};

	const kindLabel = (file) => {
		if (!file) return 'folder';
		return file.kind || (file.is_dir ? 'folder' : 'file');
	};

	const toggle = () => {
		dispatch('toggle', { path: node.path });
	};

	// Above this, ask before downloading (and, for folders, before zipping).
	const LARGE_DOWNLOAD_BYTES = 1024 * 1024 * 1024;
	let largeDownload: { url: string; size: number } | null = null;
	// Sizing a big Zarr store can take seconds; ignore clicks until it answers.
	let checkingSize = false;

	const startDownload = (url: string) => {
		// A link, not fetch: the browser saves the stream to disk as it arrives.
		const link = document.createElement('a');
		link.href = url;
		link.download = '';
		document.body.appendChild(link);
		link.click();
		document.body.removeChild(link);
	};

	/** Folders and Zarr stores download as a zip. Size is fetched when not known. */
	const download = async (path: string, zip: boolean, size: number | null = null) => {
		const url = zip ? getArtifactArchiveUrl($chatId, path) : getArtifactContentUrl($chatId, path);
		if (checkingSize) return;
		checkingSize = true;
		try {
			size ??= await getArtifactSize(localStorage.token, $chatId, path);
		} catch (e) {
			toast.error(`${e}`);
			return;
		} finally {
			checkingSize = false;
		}
		if (size > LARGE_DOWNLOAD_BYTES) largeDownload = { url, size };
		else startDownload(url);
	};

	// HTML: the full-screen viewer's "Open in new tab" link. Images: the file itself.
	const copyLink = async (path: string, kind: string) => {
		const href =
			kind === 'html' ? getArtifactViewUrl($chatId, path) : getArtifactContentUrl($chatId, path);
		const url = new URL(href, window.location.origin).href;
		if (await copyToClipboard(url)) toast.success($i18n.t('Copied link to clipboard'));
	};

	// The stamp and the crumbs open the provenance in the panel's top viewer.
	const openProvenance = () => dispatch('openProvenance', { path: file.path });

	$: file = node.file;
	// Only the kinds the server reads provenance from (artifacts._provenance_for_entry).
	$: canAskProvenance =
		!!file &&
		(file.kind === 'html' ||
			file.kind === 'zarr' ||
			(file.kind === 'image' && /\.(png|gif)$/i.test(file.path)));
	$: crumbs = file?.provenance?.length
		? file.provenance
		: file
			? ($openedCrumbs[crumbsKey($chatId, file.path, file.modified)] ?? [])
			: [];
	$: navigable = isNavigableDir(node);
	$: open = expanded.has(node.path);
	$: pad = `padding-left: ${depth * 0.75 + 0.25}rem`;
	$: selected = (file?.kind === 'image' || file?.kind === 'html') && selectedImage === file.path;
</script>

{#if navigable}
	<div class="flex flex-col">
		<div class="flex items-center gap-2 rounded-md hover:bg-black/5 dark:hover:bg-white/5">
			<button
				type="button"
				class="flex items-center gap-1 flex-1 min-w-0 text-left text-xs px-1 py-1"
				style={pad}
				on:click={toggle}
			>
				{#if open}
					<ChevronDown className="size-3 shrink-0 text-gray-400" />
				{:else}
					<ChevronRight className="size-3 shrink-0 text-gray-400" />
				{/if}
				<span class="truncate min-w-0" title={node.name}>{node.name}</span>
				<span class="text-gray-400 shrink-0">{kindLabel(file)}</span>
			</button>
			<!-- Zipping needs a sign-in: share-link visitors may be signed out. -->
			{#if $user}
				<div class="shrink-0 pr-1">
					<Tooltip content={$i18n.t('Download as zip')}>
						<button
							type="button"
							class={iconButton}
							aria-label={$i18n.t('Download as zip')}
							on:click={() => download(node.path, true)}
						>
							<ArrowDownTray className="size-3.5" />
						</button>
					</Tooltip>
				</div>
			{/if}
		</div>
		{#if open}
			{#each node.children as child}
				<svelte:self
					node={child}
					depth={depth + 1}
					{expanded}
					{selectedImage}
					on:toggle
					on:openImage
					on:openProvenance
				/>
			{/each}
		{/if}
	</div>
{:else if file?.kind === 'zarr'}
	<div class="flex flex-col gap-0.5">
		<div class="flex items-center justify-between gap-2 text-xs px-1 py-1 rounded-md" style={pad}>
			<div class="truncate flex items-center gap-1 min-w-0">
				<span class="truncate" title={node.name}>{node.name}</span>
				<span class="text-gray-400 shrink-0">zarr</span>
			</div>
			<div class="flex items-center gap-0.5 shrink-0">
				{#if canAskProvenance}
					<Tooltip content={$i18n.t('Provenance')}>
						<button
							type="button"
							class={iconButton}
							aria-label={$i18n.t('Provenance')}
							on:click={openProvenance}
						>
							<ProvenanceStamp className="size-3.5" />
						</button>
					</Tooltip>
				{/if}
				{#if $user}
					<Tooltip content={$i18n.t('Download')}>
						<button
							type="button"
							class={iconButton}
							aria-label={$i18n.t('Download')}
							on:click={() => download(file.path, true)}
						>
							<ArrowDownTray className="size-3.5" />
						</button>
					</Tooltip>
				{/if}
			</div>
		</div>
		{#if crumbs.length}
			<button
				type="button"
				class="w-full min-w-0 pb-0.5 text-left text-[10px] leading-snug text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 truncate transition"
				style={pad}
				title={crumbs.join(' → ')}
				on:click={openProvenance}>{crumbs.join(' → ')}</button
			>
		{/if}
	</div>
{:else if file}
	<div
		class="flex flex-col gap-0.5 rounded-md {selected
			? 'bg-black/5 dark:bg-white/5'
			: 'hover:bg-black/5 dark:hover:bg-white/5'}"
	>
		<div class="flex items-center justify-between gap-2 text-xs px-1 py-1" style={pad}>
			{#if file.kind === 'image' || file.kind === 'html'}
				<button
					type="button"
					class="truncate flex items-center gap-1 text-left hover:underline min-w-0"
					on:click={() => dispatch('openImage', { path: file.path })}
				>
					<span class="truncate" title={node.name}>{node.name}</span>
					<span class="text-gray-400 shrink-0">{file.kind}</span>
				</button>
			{:else}
				<div class="truncate flex items-center gap-1 min-w-0">
					<span class="truncate" title={node.name}>{node.name}</span>
					<span class="text-gray-400 shrink-0">{kindLabel(file)}</span>
				</div>
			{/if}
			<div class="flex items-center gap-0.5 shrink-0">
				{#if canAskProvenance}
					<Tooltip content={$i18n.t('Provenance')}>
						<button
							type="button"
							class={iconButton}
							aria-label={$i18n.t('Provenance')}
							on:click={openProvenance}
						>
							<ProvenanceStamp className="size-3.5" />
						</button>
					</Tooltip>
				{/if}
				{#if file.kind === 'image' || file.kind === 'html'}
					<Tooltip content={$i18n.t('Open')}>
						<button
							type="button"
							class={iconButton}
							aria-label={$i18n.t('Open')}
							on:click={() => dispatch('openImage', { path: file.path })}
						>
							<ArrowsPointingOut className="size-3.5" />
						</button>
					</Tooltip>
					<Tooltip content={$i18n.t('Copy link')}>
						<button
							type="button"
							class={iconButton}
							aria-label={$i18n.t('Copy link')}
							on:click={() => copyLink(file.path, file.kind)}
						>
							<DocumentDuplicate className="size-3.5" />
						</button>
					</Tooltip>
					<Tooltip content={$i18n.t('Download')}>
						<button
							type="button"
							class={iconButton}
							aria-label={$i18n.t('Download')}
							on:click={() => download(file.path, false, file.size)}
						>
							<ArrowDownTray className="size-3.5" />
						</button>
					</Tooltip>
				{:else if !file.is_dir}
					<Tooltip content={$i18n.t('Download')}>
						<button
							type="button"
							class={iconButton}
							aria-label={$i18n.t('Download')}
							on:click={() => download(file.path, false, file.size)}
						>
							<ArrowDownTray className="size-3.5" />
						</button>
					</Tooltip>
				{/if}
			</div>
		</div>
		{#if crumbs.length}
			<button
				type="button"
				class="w-full min-w-0 pb-0.5 text-left text-[10px] leading-snug text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 truncate transition"
				style={pad}
				title={crumbs.join(' → ')}
				on:click={openProvenance}>{crumbs.join(' → ')}</button
			>
		{/if}
	</div>
{/if}

<ConfirmDialog
	show={largeDownload !== null}
	title={$i18n.t('Large download')}
	message={$i18n.t('This download is {{size}}. It may take a while. Download anyway?', {
		size: formatFileSize(largeDownload?.size)
	})}
	confirmLabel={$i18n.t('Download')}
	on:confirm={() => {
		if (largeDownload) startDownload(largeDownload.url);
		largeDownload = null;
	}}
	on:cancel={() => (largeDownload = null)}
/>
