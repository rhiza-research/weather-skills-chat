<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { onDestroy, getContext, createEventDispatcher } from 'svelte';
	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher();

	import {
		chatId,
		settings,
		showArtifacts,
		showControls,
		chatArtifactLists,
		artifactCopy
	} from '$lib/stores';
	import {
		getArtifactContentUrl,
		getArtifactProvenance,
		getArtifactViewUrl,
		isHtmlArtifact,
		uploadChatArtifact
	} from '$lib/apis/artifacts';
	import { shouldLoadArtifactList } from '$lib/chat/artifactsList';
	import { ensureArtifacts, refreshArtifacts } from '$lib/chat/cache';
	import XMark from '../icons/XMark.svelte';
	import { copyToClipboard, createMessagesList } from '$lib/utils';
	import ArrowsPointingOut from '../icons/ArrowsPointingOut.svelte';
	import Tooltip from '../common/Tooltip.svelte';
	import SvgPanZoom from '../common/SVGPanZoom.svelte';
	import ArrowLeft from '../icons/ArrowLeft.svelte';
	import ImagePreview from '../common/ImagePreview.svelte';
	import HtmlPreview from '../common/HtmlPreview.svelte';
	import HtmlArtifactFrame from '../common/HtmlArtifactFrame.svelte';
	import ArtifactBrowser from './ArtifactBrowser.svelte';
	import { crumbsKey, openedCrumbs } from './ArtifactTreeNode.svelte';
	import { goto } from '$app/navigation';
	import ArrowUpTray from '../icons/ArrowUpTray.svelte';
	import PencilSquare from '../icons/PencilSquare.svelte';
	import { newChatWithArtifacts } from '$lib/apis/chats';
	import Spinner from '../common/Spinner.svelte';
	import ProvenanceView from './ProvenanceView.svelte';

	export let history;
	// A share link's frozen files: browse and download only.
	export let readOnly = false;
	let messages = [];

	let contents: Array<{ type: string; content: string }> = [];
	let selectedContentIdx = 0;

	let copied = false;
	let iframeElement: HTMLIFrameElement;
	let files: any[] = [];
	let selectedImage: string | null = null;
	let previewUrl: string | null = null;
	let showImageModal = false;
	// HTML artifacts (Plotly figures) load straight from the view route in a
	// sandboxed frame, not as a blob.
	let previewHtmlUrl = '';
	let showHtmlModal = false;
	// Modification time of the open file, so a skill rewriting it reloads the
	// preview when the new file list arrives.
	let previewModified: number | null = null;

	const fileModified = (path: string | null) =>
		(files.find((file) => file?.path === path)?.modified as number | undefined) ?? null;

	const htmlPreviewUrl = (path: string, modified: number | null) =>
		modified ? `${getArtifactViewUrl($chatId, path)}?v=${modified}` : getArtifactViewUrl($chatId, path);
	let modalAlt = '';

	// Set by Chat.svelte while this chat's files are copied in from another chat.
	$: copyState = $artifactCopy?.chatId === $chatId ? $artifactCopy.state : null;
	let startingChat = false;
	const startChatWithArtifacts = async () => {
		startingChat = true;
		try {
			const created = await newChatWithArtifacts(localStorage.token, $chatId);
			await goto(`/c/${created.id}`);
		} catch (error) {
			toast.error(`${error}`);
		} finally {
			startingChat = false;
		}
	};
	let uploading = false;
	let fileInput: HTMLInputElement;
	let loadingFiles = false;
	let loadQueued = false;
	let loadedArtifactKey = '';

	const revokePreview = () => {
		if (previewUrl) {
			URL.revokeObjectURL(previewUrl);
			previewUrl = null;
		}
	};

	// The current image stays up until the new one has loaded, so switching does not flash.
	const loadPreview = async (path: string) => {
		const res = await fetch(getArtifactContentUrl($chatId, path), {
			headers: { authorization: `Bearer ${localStorage.token}` }
		});
		if (path !== selectedImage) return null; // another file was opened meanwhile
		if (!res.ok) {
			revokePreview();
			toast.error($i18n.t('Could not load preview'));
			return null;
		}
		const blob = await res.blob();
		if (path !== selectedImage) return null;
		revokePreview();
		previewUrl = URL.createObjectURL(blob);
		return previewUrl;
	};

	// Opening a file while full screen keeps it full screen.
	const openImage = async (path: string) => {
		closeProvenance();
		selectedImage = path;
		modalAlt = path;
		previewModified = fileModified(path);
		if (isHtmlArtifact(path)) {
			revokePreview();
			previewHtmlUrl = htmlPreviewUrl(path, previewModified);
			showHtmlModal ||= showImageModal;
			showImageModal = false;
			return;
		}
		const url = await loadPreview(path);
		if (path !== selectedImage) return;
		previewHtmlUrl = '';
		showImageModal ||= showHtmlModal;
		showHtmlModal = false;
		if (!url) showImageModal = false;
	};

	// Left / right step through the open file's folder of images and plots, in list order.
	const stepPreview = async (event: KeyboardEvent) => {
		const current = selectedImage;
		if (!current || (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight')) return;
		if ((event.target as HTMLElement)?.closest?.('input, textarea, [contenteditable]')) return;
		const dir = (path: string) => path.slice(0, path.lastIndexOf('/') + 1);
		const media = files
			.filter(
				(file) =>
					(file?.kind === 'image' || file?.kind === 'html') && dir(file.path) === dir(current)
			)
			.sort((a, b) => a.path.localeCompare(b.path));
		const i = media.findIndex((file) => file.path === current);
		const next = media[i + (event.key === 'ArrowRight' ? 1 : -1)];
		if (!next) return;
		event.preventDefault();
		openImage(next.path);
	};

	const clearPreview = () => {
		selectedImage = null;
		modalAlt = '';
		showImageModal = false;
		showHtmlModal = false;
		previewHtmlUrl = '';
		previewModified = null;
		revokePreview();
	};

	const expandPreview = () => {
		if (previewHtmlUrl) {
			showHtmlModal = true;
		} else if (previewUrl) {
			showImageModal = true;
		}
	};

	$: previewTitle = selectedImage || modalAlt || '';

	// Provenance opened from a file's stamp or crumbs takes the top viewer until it is
	// closed or a file is opened; a rewritten file loads it again.
	let provenancePath: string | null = null;
	let provenance: any[] | null = null;
	let provenanceModified: number | null = null;
	let provenanceFullscreen = false;
	let provenanceMode: 'graph' | 'text' = 'graph';

	const openProvenance = async (path: string) => {
		const modified = fileModified(path);
		if (path === provenancePath && modified === provenanceModified && provenance) return;
		provenancePath = path;
		provenanceModified = modified;
		provenance = null;
		try {
			const res = await getArtifactProvenance(localStorage.token, $chatId, path);
			const branches = res?.branches;
			if (path !== provenancePath) return;
			if (branches?.length) {
				provenance = branches;
				if (Array.isArray(res?.crumbs) && res.crumbs.length)
					openedCrumbs.update((all) => ({ ...all, [crumbsKey($chatId, path, modified)]: res.crumbs }));
			} else {
				closeProvenance();
				toast.info($i18n.t('No provenance recorded for this file.'));
			}
		} catch (e) {
			console.error(e);
			if (path !== provenancePath) return;
			closeProvenance();
			toast.error($i18n.t('Could not load provenance.'));
		}
	};

	const closeProvenance = () => {
		provenancePath = null;
		provenance = null;
		provenanceModified = null;
		provenanceFullscreen = false;
	};

	$: if (provenancePath && files) {
		const modified = fileModified(provenancePath);
		if (modified && provenanceModified && modified !== provenanceModified)
			openProvenance(provenancePath);
	}

	// The open file was rewritten (new list from chat:artifacts): reload it.
	$: if (selectedImage && files) {
		const modified = fileModified(selectedImage);
		if (modified && previewModified === null) {
			previewModified = modified;
		} else if (modified && modified !== previewModified) {
			previewModified = modified;
			if (isHtmlArtifact(selectedImage)) {
				previewHtmlUrl = htmlPreviewUrl(selectedImage, modified);
			} else {
				loadPreview(selectedImage);
			}
		}
	}
	$: hasPreview = !!previewUrl || !!previewHtmlUrl || !!provenancePath;

	const closePanel = () => {
		showArtifacts.set(false);
		showControls.set(false);
		dispatch('close');
	};

	const loadFiles = async () => {
		if (!$chatId || $chatId === 'local') {
			files = [];
			return;
		}
		if (loadingFiles) {
			loadQueued = true;
			return;
		}
		loadingFiles = true;
		try {
			const id = $chatId;
			const listed = await refreshArtifacts(localStorage.token, id);
			// The user may have switched chats while this was in flight.
			if (id === $chatId) files = Array.isArray(listed) ? listed : [];
		} catch (e) {
			files = [];
			loadedArtifactKey = '';
			console.error(e);
		} finally {
			loadingFiles = false;
			if (loadQueued) {
				loadQueued = false;
				await loadFiles();
			}
		}
	};

	const onUpload = async (e: Event) => {
		const input = e.currentTarget as HTMLInputElement;
		const file = input.files?.[0];
		if (!file) return;
		if (!$chatId || $chatId === 'local') {
			toast.error($i18n.t('Save the chat before uploading artifacts.'));
			input.value = '';
			return;
		}
		uploading = true;
		try {
			await uploadChatArtifact(localStorage.token, $chatId, file.name, file);
			await loadFiles();
			toast.success($i18n.t('Uploaded {{NAME}}', { NAME: file.name }));
			if (/\.(png|jpe?g|gif|webp)$/i.test(file.name)) {
				await openImage(file.name);
			}
		} catch (err) {
			console.error(err);
			toast.error(`${err?.detail ?? err ?? 'Upload failed'}`);
		} finally {
			uploading = false;
			input.value = '';
		}
	};

	// A cached file list paints with the transcript. Fetch only when this chat
	// has no list yet. Later changes arrive on chat:artifacts, or from an upload.
	$: {
		if ($showArtifacts && $chatId && $chatId !== 'local') {
			const listed = $chatArtifactLists[$chatId];
			if (Array.isArray(listed)) {
				files = listed;
				loadedArtifactKey = $chatId;
			} else if (shouldLoadArtifactList(listed) && loadedArtifactKey !== $chatId) {
				loadedArtifactKey = $chatId;
				// Drop the previous chat's list so it doesn't show while this one loads.
				files = [];
				loadFiles();
			}
		} else {
			if (!$chatId || $chatId === 'local') files = [];
			loadedArtifactKey = '';
		}
	}

	$: if (history) {
		messages = createMessagesList(history, history.currentId);
		getContents();
	} else {
		messages = [];
		getContents();
	}

	const getContents = () => {
		contents = [];
		messages.forEach((message) => {
			if (message?.role !== 'user' && message?.content) {
				const codeBlockContents = message.content.match(/```[\s\S]*?```/g);
				let codeBlocks = [];

				if (codeBlockContents) {
					codeBlockContents.forEach((block) => {
						const lang = block.split('\n')[0].replace('```', '').trim().toLowerCase();
						const code = block.replace(/```[\s\S]*?\n/, '').replace(/```$/, '');
						codeBlocks.push({ lang, code });
					});
				}

				let htmlContent = '';
				let cssContent = '';
				let jsContent = '';

				codeBlocks.forEach((block) => {
					const { lang, code } = block;

					if (lang === 'html') {
						htmlContent += code + '\n';
					} else if (lang === 'css') {
						cssContent += code + '\n';
					} else if (lang === 'javascript' || lang === 'js') {
						jsContent += code + '\n';
					}
				});

				const inlineHtml = message.content.match(/<html>[\s\S]*?<\/html>/gi);
				const inlineCss = message.content.match(/<style>[\s\S]*?<\/style>/gi);
				const inlineJs = message.content.match(/<script>[\s\S]*?<\/script>/gi);

				if (inlineHtml) {
					inlineHtml.forEach((block) => {
						const content = block.replace(/<\/?html>/gi, '');
						htmlContent += content + '\n';
					});
				}
				if (inlineCss) {
					inlineCss.forEach((block) => {
						const content = block.replace(/<\/?style>/gi, '');
						cssContent += content + '\n';
					});
				}
				if (inlineJs) {
					inlineJs.forEach((block) => {
						const content = block.replace(/<\/?script>/gi, '');
						jsContent += content + '\n';
					});
				}

				if (htmlContent || cssContent || jsContent) {
					const renderedContent = `
                        <!DOCTYPE html>
                        <html lang="en">
                        <head>
                            <meta charset="UTF-8">
                            <meta name="viewport" content="width=device-width, initial-scale=1.0">
							<${''}style>
								body {
									background-color: white;
								}

								${cssContent}
							</${''}style>
                        </head>
                        <body>
                            ${htmlContent}

                            <${''}script>
                                ${jsContent}
                            </${''}script>
                        </body>
                        </html>
                    `;
					contents = [...contents, { type: 'iframe', content: renderedContent }];
				}

				codeBlocks.forEach((block) => {
					if (block.lang === 'svg' || (block.lang === 'xml' && block.code.includes('<svg'))) {
						contents = [...contents, { type: 'svg', content: block.code }];
					}
				});
			}
		});

		selectedContentIdx = contents ? contents.length - 1 : 0;
	};

	function navigateContent(direction: 'prev' | 'next') {
		selectedContentIdx =
			direction === 'prev'
				? Math.max(selectedContentIdx - 1, 0)
				: Math.min(selectedContentIdx + 1, contents.length - 1);
	}

	const iframeLoadHandler = () => {
		iframeElement.contentWindow.addEventListener(
			'click',
			function (e) {
				const target = e.target.closest('a');
				if (target && target.href) {
					e.preventDefault();
					const url = new URL(target.href, iframeElement.baseURI);
					if (url.origin === window.location.origin) {
						iframeElement.contentWindow.history.pushState(
							null,
							'',
							url.pathname + url.search + url.hash
						);
					}
				}
			},
			true
		);
	};

	const showFullScreen = () => {
		if (iframeElement.requestFullscreen) {
			iframeElement.requestFullscreen();
		} else if (iframeElement.webkitRequestFullscreen) {
			iframeElement.webkitRequestFullscreen();
		} else if (iframeElement.msRequestFullscreen) {
			iframeElement.msRequestFullscreen();
		}
	};

	onDestroy(() => {
		revokePreview();
	});
</script>

<svelte:window on:keydown={stepPreview} />

<ImagePreview
	bind:show={showImageModal}
	src={previewUrl || ''}
	alt={modalAlt}
/>

<HtmlPreview
	bind:show={showHtmlModal}
	src={previewHtmlUrl}
	downloadUrl={selectedImage && $chatId ? getArtifactContentUrl($chatId, selectedImage) : ''}
	title={modalAlt}
/>

<div class="w-full h-full max-h-full relative flex flex-col bg-gray-50 dark:bg-gray-850 min-h-0 overflow-hidden">
	{#if hasPreview}
		<div
			class="flex flex-col min-h-0 shrink-0 {contents.length > 0
				? 'h-[38%]'
				: 'h-1/2'} border-b border-gray-100 dark:border-gray-800"
		>
			<div class="flex items-start justify-between gap-2 px-2.5 py-1.5 shrink-0">
				<div class="text-xs leading-4 py-[3px] text-gray-600 dark:text-gray-300 break-words min-w-0">
					{provenancePath ? `${$i18n.t('Provenance')}: ${provenancePath}` : previewTitle}
				</div>
				<div class="flex items-center gap-0.5 shrink-0">
					<Tooltip content={$i18n.t('Open in full screen')}>
						<button
							type="button"
							class="p-1 rounded-md text-gray-500 hover:text-gray-800 dark:hover:text-gray-200 hover:bg-black/5 dark:hover:bg-white/5"
							on:click={() => (provenancePath ? (provenanceFullscreen = true) : expandPreview())}
							aria-label={$i18n.t('Expand image')}
						>
							<ArrowsPointingOut className="size-3.5" />
						</button>
					</Tooltip>
					<button
						type="button"
						class="p-1 rounded-md text-gray-500 hover:text-gray-800 dark:hover:text-gray-200 hover:bg-black/5 dark:hover:bg-white/5"
						on:click={() => (provenancePath ? closeProvenance() : clearPreview())}
						aria-label={$i18n.t('Close preview')}
					>
						<XMark className="size-3.5" />
					</button>
				</div>
			</div>
			{#if provenancePath}
				<div class="flex-1 min-h-0 w-full px-2.5 pb-2">
					{#if provenance}
						<ProvenanceView
							branches={provenance}
							fileName={provenancePath.split('/').pop() ?? ''}
							title={provenancePath}
							fill
							fullscreenButton={false}
							bind:mode={provenanceMode}
							bind:fullscreen={provenanceFullscreen}
						/>
					{:else}
						<div class="flex items-center gap-1.5 text-xs text-gray-400">
							{$i18n.t('Loading provenance')}
							<Spinner className="size-3" />
						</div>
					{/if}
				</div>
			{:else if previewHtmlUrl}
				<div
					class="flex-1 min-h-0 w-full overflow-hidden px-2 pb-2"
				>
					<div
						class="h-full w-full overflow-hidden rounded border border-gray-100 dark:border-gray-800"
					>
						<HtmlArtifactFrame
							src={previewHtmlUrl}
							title={previewTitle}
							fit="contain"
							lazy={false}
						/>
					</div>
				</div>
			{:else}
				<button
					type="button"
					class="flex-1 min-h-0 w-full flex items-center justify-center overflow-hidden px-2 pb-2 cursor-zoom-in"
					on:click={expandPreview}
				>
					<img
						class="max-w-full max-h-full object-contain rounded border border-gray-100 dark:border-gray-800 bg-white dark:bg-gray-900"
						src={previewUrl}
						alt={previewTitle || 'preview'}
					/>
				</button>
			{/if}
		</div>
	{/if}

	<div class="flex flex-col min-h-0 flex-1 overflow-hidden @container">
		<!-- mt-2 h-9 centres the row on the chat navbar's 36px buttons, which start 8px down. -->
		<div class="flex items-center justify-between gap-2 px-3 mt-2 h-9 shrink-0">
			<div class="text-sm font-medium">{$i18n.t('Artifacts')}</div>
			<!-- The full row measures about 392px; narrower than 400px, the new-chat button drops its label. -->
			<div class="flex items-center gap-3 whitespace-nowrap">
				{#if !readOnly && !copyState && files.length > 0 && $chatId && $chatId !== 'local'}
					<Tooltip content={$i18n.t('Start a new chat with a copy of these artifacts')} placement="bottom">
						<button
							type="button"
							class="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 disabled:opacity-50"
							disabled={startingChat}
							on:click={startChatWithArtifacts}
							aria-label={$i18n.t('New chat with these artifacts')}
						>
							<PencilSquare className="size-4" strokeWidth="2" />
							<span class="hidden @min-[400px]:inline">{$i18n.t('New chat with these artifacts')}</span>
						</button>
					</Tooltip>
				{/if}
				{#if !readOnly && copyState !== 'copying'}
					<Tooltip
						placement="bottom"
						content={uploading
							? $i18n.t('Uploading...')
							: $i18n.t("Upload a file to this chat's artifacts")}
					>
						<button
							type="button"
							class="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 disabled:opacity-50"
							disabled={uploading || !$chatId || $chatId === 'local'}
							on:click={() => fileInput?.click()}
						>
							<ArrowUpTray className="size-4" strokeWidth="2" />
							{uploading ? $i18n.t('Uploading...') : $i18n.t('Upload')}
						</button>
					</Tooltip>
					<input
						bind:this={fileInput}
						type="file"
						class="hidden"
						on:change={onUpload}
					/>
				{/if}
				<Tooltip content={$i18n.t('Close artifacts')} placement="bottom">
					<button
						type="button"
						class="p-0.5 text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
						on:click={closePanel}
						aria-label={$i18n.t('Close artifacts')}
					>
						<XMark className="size-3.5" />
					</button>
				</Tooltip>
			</div>
		</div>

		<div class="flex flex-col gap-2 flex-1 min-h-0 overflow-y-auto overscroll-contain px-3 pb-3">
			{#if copyState === 'copying'}
				<div class="flex items-center gap-2 text-xs text-gray-500" role="status">
					<Spinner className="size-3.5" />
					{$i18n.t('Artifact copy in progress...')}
				</div>
			{:else if copyState === 'failed'}
				<div class="text-xs text-red-600 dark:text-red-400" role="alert">
					{$i18n.t('Artifact copy failed, please try again')}
				</div>
			{/if}
			{#if copyState !== 'copying'}
				<ArtifactBrowser
					{files}
					{selectedImage}
					loading={loadingFiles && !Array.isArray($chatArtifactLists[$chatId])}
					on:openImage={(e) => openImage(e.detail.path)}
					on:openProvenance={(e) => openProvenance(e.detail.path)}
				/>
			{/if}
		</div>

		{#if contents.length > 0}
			<div
				class="pointer-events-auto z-20 flex justify-between items-center p-2.5 font-primar text-gray-900 dark:text-white shrink-0"
			>
				<button
					type="button"
					class="self-center pointer-events-auto p-1 rounded-full bg-white dark:bg-gray-850"
					on:click={() => {
						showArtifacts.set(false);
					}}
				>
					<ArrowLeft className="size-3.5  text-gray-900 dark:text-white" />
				</button>

				<div class="flex-1 flex items-center justify-between">
					<div class="flex items-center space-x-2">
						<div class="flex items-center gap-0.5 self-center min-w-fit" dir="ltr">
							<button
								type="button"
								class="self-center p-1 hover:bg-black/5 dark:hover:bg-white/5 dark:hover:text-white hover:text-black rounded-md transition disabled:cursor-not-allowed"
								on:click={() => navigateContent('prev')}
								disabled={contents.length <= 1}
							>
								<svg
									xmlns="http://www.w3.org/2000/svg"
									fill="none"
									viewBox="0 0 24 24"
									stroke="currentColor"
									stroke-width="2.5"
									class="size-3.5"
								>
									<path
										stroke-linecap="round"
										stroke-linejoin="round"
										d="M15.75 19.5 8.25 12l7.5-7.5"
									/>
								</svg>
							</button>

							<div class="text-xs self-center dark:text-gray-100 min-w-fit">
								{$i18n.t('Version {{selectedVersion}} of {{totalVersions}}', {
									selectedVersion: selectedContentIdx + 1,
									totalVersions: contents.length
								})}
							</div>

							<button
								type="button"
								class="self-center p-1 hover:bg-black/5 dark:hover:bg-white/5 dark:hover:text-white hover:text-black rounded-md transition disabled:cursor-not-allowed"
								on:click={() => navigateContent('next')}
								disabled={contents.length <= 1}
							>
								<svg
									xmlns="http://www.w3.org/2000/svg"
									fill="none"
									viewBox="0 0 24 24"
									stroke="currentColor"
									stroke-width="2.5"
									class="size-3.5"
								>
									<path
										stroke-linecap="round"
										stroke-linejoin="round"
										d="m8.25 4.5 7.5 7.5-7.5 7.5"
									/>
								</svg>
							</button>
						</div>
					</div>

					<div class="flex items-center gap-1">
						<button
							type="button"
							class="copy-code-button bg-none border-none text-xs bg-gray-50 hover:bg-gray-100 dark:bg-gray-850 dark:hover:bg-gray-800 transition rounded-md px-1.5 py-0.5"
							on:click={() => {
								copyToClipboard(contents[selectedContentIdx].content);
								copied = true;
								setTimeout(() => {
									copied = false;
								}, 2000);
							}}>{copied ? $i18n.t('Copied') : $i18n.t('Copy')}</button
						>

						{#if contents[selectedContentIdx].type === 'iframe'}
							<Tooltip content={$i18n.t('Open in full screen')}>
								<button
									type="button"
									class=" bg-none border-none text-xs bg-gray-50 hover:bg-gray-100 dark:bg-gray-850 dark:hover:bg-gray-800 transition rounded-md p-0.5"
									on:click={showFullScreen}
								>
									<ArrowsPointingOut className="size-3.5" />
								</button>
							</Tooltip>
						{/if}
					</div>
				</div>

				<button
					type="button"
					class="self-center pointer-events-auto p-1 rounded-full bg-white dark:bg-gray-850"
					on:click={closePanel}
				>
					<XMark className="size-3.5 text-gray-900 dark:text-white" />
				</button>
			</div>

			<div class="flex-1 w-full min-h-0 {hasPreview ? 'max-h-[30%]' : ''}">
				{#if contents[selectedContentIdx].type === 'iframe'}
					<iframe
						bind:this={iframeElement}
						title={$i18n.t('Content')}
						srcdoc={contents[selectedContentIdx].content}
						class="w-full border-0 h-full rounded-none"
						sandbox="allow-scripts{($settings?.iframeSandboxAllowForms ?? false)
							? ' allow-forms'
							: ''}{($settings?.iframeSandboxAllowSameOrigin ?? false)
							? ' allow-same-origin'
							: ''}"
						on:load={iframeLoadHandler}
					></iframe>
				{:else if contents[selectedContentIdx].type === 'svg'}
					<SvgPanZoom
						className=" w-full h-full max-h-full overflow-hidden"
						svg={contents[selectedContentIdx].content}
					/>
				{/if}
			</div>
		{/if}
	</div>
</div>
