<script lang="ts">
	import { getContext } from 'svelte';
	import ArtifactTreeNode from './ArtifactTreeNode.svelte';

	const i18n = getContext('i18n');

	export let files: any[] = [];
	export let selectedImage: string | null = null;
	export let selectedView: string | null = null;

	type TreeNode = {
		name: string;
		path: string;
		file: any | null;
		children: TreeNode[];
	};

	let expanded: Set<string> = new Set();

	const parentPath = (path: string) => {
		const idx = path.lastIndexOf('/');
		return idx === -1 ? '' : path.slice(0, idx);
	};

	const ensureAncestorsExpanded = (path: string | null | undefined) => {
		if (!path) return;
		let cur = parentPath(path);
		const next = new Set(expanded);
		let changed = false;
		while (cur) {
			if (!next.has(cur)) {
				next.add(cur);
				changed = true;
			}
			cur = parentPath(cur);
		}
		if (changed) expanded = next;
	};

	$: if (selectedImage) ensureAncestorsExpanded(selectedImage);
	$: if (selectedView) ensureAncestorsExpanded(selectedView);

	const isNavigableDir = (node: TreeNode) => {
		const kind = node.file?.kind;
		if (kind === 'zarr') return false;
		if (kind === 'directory' || node.file?.is_dir) return true;
		return node.children.length > 0 && !node.file;
	};

	const buildTree = (entries: any[]): TreeNode[] => {
		const root: TreeNode = { name: '', path: '', file: null, children: [] };
		const nodes = new Map<string, TreeNode>([['', root]]);

		const ensureNode = (path: string, name: string): TreeNode => {
			let node = nodes.get(path);
			if (node) return node;
			node = { name, path, file: null, children: [] };
			nodes.set(path, node);
			const parent = parentPath(path);
			const parentName = parent.includes('/') ? parent.slice(parent.lastIndexOf('/') + 1) : parent;
			const parentNode = ensureNode(parent, parentName);
			parentNode.children.push(node);
			return node;
		};

		const sortNodes = (list: TreeNode[]) => {
			list.sort((a, b) => {
				const aDir = isNavigableDir(a);
				const bDir = isNavigableDir(b);
				if (aDir !== bDir) return aDir ? -1 : 1;
				return a.name.localeCompare(b.name);
			});
			for (const child of list) sortNodes(child.children);
		};

		const zarrPaths = new Set(
			(entries || []).filter((f) => f?.kind === 'zarr' && f.path).map((f) => f.path)
		);

		for (const file of entries || []) {
			const path = file?.path;
			if (!path) continue;
			// Linked views are rendered under their zarr node.
			if (file.kind === 'zarr_view' && file.zarr && zarrPaths.has(file.zarr)) {
				continue;
			}
			const parts = path.split('/').filter(Boolean);
			let acc = '';
			for (let i = 0; i < parts.length; i++) {
				acc = acc ? `${acc}/${parts[i]}` : parts[i];
				const node = ensureNode(acc, parts[i]);
				if (i === parts.length - 1) {
					node.file = file;
				}
			}
		}

		sortNodes(root.children);
		return root.children;
	};

	$: tree = buildTree(files);

	const onToggle = (e: CustomEvent<{ path: string }>) => {
		const path = e.detail?.path;
		if (!path) return;
		const next = new Set(expanded);
		if (next.has(path)) next.delete(path);
		else next.add(path);
		expanded = next;
	};
</script>

{#if tree.length === 0}
	<div class="text-[11px] text-gray-400">{$i18n.t('No files in this chat yet.')}</div>
{:else}
	<div class="flex flex-col gap-0.5">
		{#each tree as node (node.path)}
			<ArtifactTreeNode
				{node}
				depth={0}
				{files}
				{expanded}
				{selectedImage}
				{selectedView}
				on:toggle={onToggle}
				on:openImage
				on:openView
			/>
		{/each}
	</div>
{/if}
