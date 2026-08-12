<script lang="ts">
	import { SvelteFlowProvider } from '@xyflow/svelte';
	import { Pane, PaneResizer } from 'paneforge';

	import { onDestroy, onMount, tick } from 'svelte';
	import { showControls, showCallOverlay, showOverview, showArtifacts } from '$lib/stores';

	import Controls from './Controls/Controls.svelte';
	import CallOverlay from './MessageInput/CallOverlay.svelte';
	import Drawer from '../common/Drawer.svelte';
	import Overview from './Overview.svelte';
	import EllipsisVertical from '../icons/EllipsisVertical.svelte';
	import Artifacts from './Artifacts.svelte';

	export let history;
	export let models = [];

	export let chatId = null;

	export let chatFiles = [];
	export let params = {};

	export let eventTarget: EventTarget;
	export let submitPrompt: Function;
	export let stopResponse: Function;
	export let showMessage: Function;
	export let files;
	export let modelId;

	export let pane;

	let mediaQuery;
	let largeScreen =
		typeof window !== 'undefined' ? window.matchMedia('(min-width: 768px)').matches : true;

	let minSize = 25;
	const DEFAULT_SIZE = 30;
	const MAX_SIZE = 45;

	const readStoredSize = () => {
		const stored = parseInt(localStorage?.chatControlsSize);
		if (!stored || Number.isNaN(stored) || stored < minSize || stored > MAX_SIZE) {
			return DEFAULT_SIZE;
		}
		return stored;
	};

	export const openPane = () => {
		if (!pane) return;
		try {
			const size = readStoredSize();
			pane.resize(Math.max(minSize, Math.min(MAX_SIZE, size)));
		} catch (e) {
			// Pane may not be ready yet.
		}
	};

	const handleMediaQuery = async (e) => {
		const wasLarge = largeScreen;
		largeScreen = e.matches;

		if ($showCallOverlay) {
			showCallOverlay.set(false);
			await tick();
			showCallOverlay.set(true);
		}

		if (!wasLarge && largeScreen && $showControls) {
			await tick();
			openPane();
		}

		if (!largeScreen) {
			pane = null;
		}
	};

	onMount(() => {
		mediaQuery = window.matchMedia('(min-width: 768px)');
		mediaQuery.addEventListener('change', handleMediaQuery);
		largeScreen = mediaQuery.matches;

		const container = document.getElementById('chat-container');
		if (container?.clientWidth) {
			minSize = Math.min(
				DEFAULT_SIZE,
				Math.max(20, Math.floor((320 / container.clientWidth) * 100))
			);
		}

		const resizeObserver = new ResizeObserver((entries) => {
			for (let entry of entries) {
				const width = entry.contentRect.width;
				if (!width) continue;
				minSize = Math.min(
					DEFAULT_SIZE,
					Math.max(20, Math.floor((320 / width) * 100))
				);

				if ($showControls && pane && typeof pane.isExpanded === 'function' && pane.isExpanded()) {
					const size = pane.getSize?.() ?? 0;
					if (size > 0 && size < minSize) {
						pane.resize(minSize);
					}
				}
			}
		});

		if (container) {
			resizeObserver.observe(container);
		}

		if (largeScreen && $showControls) {
			tick().then(() => openPane());
		}

		return () => {
			resizeObserver.disconnect();
		};
	});

	onDestroy(() => {
		// Do not clear showControls/showArtifacts here — destroying/remounting
		// the pane during chat load was wiping state and fighting openArtifactsPanel.
		mediaQuery?.removeEventListener('change', handleMediaQuery);
	});

	const clearPanelFlags = () => {
		showControls.set(false);
		showOverview.set(false);
		showArtifacts.set(false);
		if ($showCallOverlay) {
			showCallOverlay.set(false);
		}
	};

	// When chat id is cleared, hide the panel.
	$: if (!chatId) {
		clearPanelFlags();
	}
</script>

<SvelteFlowProvider>
	{#if !largeScreen}
		{#if $showControls}
			<Drawer
				show={$showControls}
				on:close={() => {
					showControls.set(false);
					showArtifacts.set(false);
				}}
			>
				<div
					class=" {$showCallOverlay || $showOverview || $showArtifacts
						? ' h-screen  w-full'
						: 'px-6 py-4'} h-full"
				>
					{#if $showCallOverlay}
						<div
							class=" h-full max-h-[100dvh] bg-white text-gray-700 dark:bg-black dark:text-gray-300 flex justify-center"
						>
							<CallOverlay
								bind:files
								{submitPrompt}
								{stopResponse}
								{modelId}
								{chatId}
								{eventTarget}
								on:close={() => {
									showControls.set(false);
								}}
							/>
						</div>
					{:else if $showArtifacts}
						<div class="h-full max-h-[100dvh] min-h-0 overflow-hidden">
							<Artifacts {history} />
						</div>
					{:else if $showOverview}
						<Overview
							{history}
							on:nodeclick={(e) => {
								showMessage(e.detail.node.data.message);
							}}
							on:close={() => {
								showControls.set(false);
							}}
						/>
					{:else}
						<Controls
							on:close={() => {
								showControls.set(false);
							}}
							{models}
							bind:chatFiles
							bind:params
						/>
					{/if}
				</div>
			</Drawer>
		{/if}
	{:else}
		{#if $showControls}
			<PaneResizer class="relative flex w-2 items-center justify-center bg-background group">
				<div class="z-10 flex h-7 w-5 items-center justify-center rounded-xs">
					<EllipsisVertical className="size-4 invisible group-hover:visible" />
				</div>
			</PaneResizer>
		{/if}

		<Pane
			bind:pane
			defaultSize={$showControls ? DEFAULT_SIZE : 0}
			minSize={minSize}
			maxSize={MAX_SIZE}
			onResize={(size) => {
				if ($showControls && pane?.isExpanded?.()) {
					if (size >= minSize && size <= MAX_SIZE) {
						localStorage.chatControlsSize = size;
					}
				}
			}}
			onCollapse={() => {
				// User dragged the pane closed — sync UI only.
				// Preference is written by the navbar/close button.
				showControls.set(false);
				showArtifacts.set(false);
			}}
			collapsible={true}
			class="z-10 h-full min-h-0 bg-gray-50 dark:bg-gray-850 border-l border-gray-100 dark:border-gray-800"
		>
			{#if $showControls}
				<div class="flex h-full max-h-full min-h-0 w-full overflow-hidden">
					<div
						class="w-full h-full min-h-0 {($showOverview || $showArtifacts) && !$showCallOverlay
							? 'overflow-hidden'
							: 'px-4 py-4 bg-white dark:shadow-lg dark:bg-gray-850 border border-gray-100 dark:border-gray-850 overflow-y-auto scrollbar-hidden'} z-40 pointer-events-auto"
					>
						{#if $showCallOverlay}
							<div class="w-full h-full flex justify-center">
								<CallOverlay
									bind:files
									{submitPrompt}
									{stopResponse}
									{modelId}
									{chatId}
									{eventTarget}
									on:close={() => {
										showControls.set(false);
									}}
								/>
							</div>
						{:else if $showArtifacts}
							<div class="h-full max-h-full min-h-0 overflow-hidden">
								<Artifacts {history} />
							</div>
						{:else if $showOverview}
							<Overview
								{history}
								on:nodeclick={(e) => {
									if (e.detail.node.data.message.favorite) {
										history.messages[e.detail.node.data.message.id].favorite = true;
									} else {
										history.messages[e.detail.node.data.message.id].favorite = null;
									}

									showMessage(e.detail.node.data.message);
								}}
								on:close={() => {
									showControls.set(false);
								}}
							/>
						{:else}
							<Controls
								on:close={() => {
									showControls.set(false);
								}}
								{models}
								bind:chatFiles
								bind:params
							/>
						{/if}
					</div>
				</div>
			{/if}
		</Pane>
	{/if}
</SvelteFlowProvider>
