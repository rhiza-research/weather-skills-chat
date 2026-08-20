<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { onDestroy, getContext, createEventDispatcher } from 'svelte';
	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher();

	import { chatId, settings, showArtifacts, showControls, artifactsRefresh } from '$lib/stores';
	import {
		getArtifactContentUrl,
		getChatArtifacts,
		getZarrRenderUrl,
		uploadChatArtifact
	} from '$lib/apis/artifacts';
	import XMark from '../icons/XMark.svelte';
	import { copyToClipboard, createMessagesList } from '$lib/utils';
	import ArrowsPointingOut from '../icons/ArrowsPointingOut.svelte';
	import Tooltip from '../common/Tooltip.svelte';
	import SvgPanZoom from '../common/SVGPanZoom.svelte';
	import ArrowLeft from '../icons/ArrowLeft.svelte';
	import ImagePreview from '../common/ImagePreview.svelte';
	import ArtifactBrowser from './ArtifactBrowser.svelte';

	export let history;
	let messages = [];

	let contents: Array<{ type: string; content: string }> = [];
	let selectedContentIdx = 0;

	let copied = false;
	let iframeElement: HTMLIFrameElement;
	let files = [];
	let selectedView = null;
	let selectedImage = null;
	let previewUrl = null;
	let showImageModal = false;
	let modalAlt = '';
	let uploading = false;
	let fileInput: HTMLInputElement;
	let pollId: ReturnType<typeof setInterval> | null = null;
	let loadingFiles = false;
	let loadQueued = false;

	const clearPoll = () => {
		if (pollId != null) {
			clearInterval(pollId);
			pollId = null;
		}
	};

	const revokePreview = () => {
		if (previewUrl) {
			URL.revokeObjectURL(previewUrl);
			previewUrl = null;
		}
	};

	const loadPreview = async (url: string) => {
		revokePreview();
		const res = await fetch(url, {
			headers: { authorization: `Bearer ${localStorage.token}` }
		});
		if (!res.ok) {
			toast.error($i18n.t('Could not load preview'));
			return null;
		}
		previewUrl = URL.createObjectURL(await res.blob());
		return previewUrl;
	};

	const openImage = async (path: string) => {
		selectedImage = path;
		selectedView = null;
		showImageModal = false;
		const url = await loadPreview(getArtifactContentUrl($chatId, path));
		if (!url) return;
		modalAlt = path;
	};

	const openView = async (path: string, title: string = '') => {
		selectedView = path;
		selectedImage = null;
		showImageModal = false;
		const url = await loadPreview(getZarrRenderUrl($chatId, path));
		if (!url) return;
		modalAlt = title || path;
	};

	const clearPreview = () => {
		selectedImage = null;
		selectedView = null;
		modalAlt = '';
		showImageModal = false;
		revokePreview();
	};

	const expandPreview = () => {
		if (previewUrl) {
			showImageModal = true;
		}
	};

	$: previewTitle = selectedView || selectedImage || modalAlt || '';
	$: hasPreview = !!previewUrl;

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
			files = await getChatArtifacts(localStorage.token, $chatId);
		} catch (e) {
			files = [];
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

	// Reload when the panel opens / chat changes / an explicit refresh is requested,
	// and keep polling while open so skill writes show up without collapsing the pane.
	$: {
		clearPoll();
		if ($showArtifacts && $chatId && $chatId !== 'local') {
			void $artifactsRefresh;
			loadFiles();
			pollId = setInterval(() => {
				loadFiles();
			}, 2000);
		} else if (!$chatId || $chatId === 'local') {
			files = [];
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
		clearPoll();
		revokePreview();
	});
</script>

<ImagePreview
	bind:show={showImageModal}
	src={previewUrl || ''}
	alt={modalAlt}
/>

<div class="w-full h-full max-h-full relative flex flex-col bg-gray-50 dark:bg-gray-850 min-h-0 overflow-hidden">
	{#if hasPreview}
		<div
			class="flex flex-col min-h-0 shrink-0 {contents.length > 0
				? 'h-[38%]'
				: 'h-1/2'} border-b border-gray-100 dark:border-gray-800"
		>
			<div class="flex items-center justify-between gap-2 px-2.5 py-1.5 shrink-0">
				<div class="text-[11px] text-gray-600 dark:text-gray-300 truncate min-w-0" title={previewTitle}>
					{previewTitle}
				</div>
				<div class="flex items-center gap-0.5 shrink-0">
					<Tooltip content={$i18n.t('Open in full screen')}>
						<button
							type="button"
							class="p-1 rounded-md text-gray-500 hover:text-gray-800 dark:hover:text-gray-200 hover:bg-black/5 dark:hover:bg-white/5"
							on:click={expandPreview}
							aria-label="Expand image"
						>
							<ArrowsPointingOut className="size-3.5" />
						</button>
					</Tooltip>
					<button
						type="button"
						class="p-1 rounded-md text-gray-500 hover:text-gray-800 dark:hover:text-gray-200 hover:bg-black/5 dark:hover:bg-white/5"
						on:click={clearPreview}
						aria-label="Close preview"
					>
						<XMark className="size-3.5" />
					</button>
				</div>
			</div>
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
		</div>
	{/if}

	<div class="flex flex-col min-h-0 flex-1 overflow-hidden">
		<div class="flex items-center justify-between px-3 pt-3 pb-2 shrink-0">
			<div class="text-xs font-medium">{$i18n.t('Artifacts')}</div>
			<div class="flex items-center gap-2">
				<button
					type="button"
					class="text-xs text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 disabled:opacity-50"
					disabled={uploading || !$chatId || $chatId === 'local'}
					on:click={() => fileInput?.click()}
				>
					{uploading ? $i18n.t('Uploading...') : $i18n.t('Upload')}
				</button>
				<input
					bind:this={fileInput}
					type="file"
					class="hidden"
					on:change={onUpload}
				/>
				<button
					type="button"
					class="p-0.5 text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
					on:click={closePanel}
					aria-label="Close artifacts"
				>
					<XMark className="size-3.5" />
				</button>
			</div>
		</div>

		<div class="flex flex-col gap-2 flex-1 min-h-0 overflow-y-auto overscroll-contain px-3 pb-3">
			<ArtifactBrowser
				{files}
				{selectedImage}
				{selectedView}
				on:openImage={(e) => openImage(e.detail.path)}
				on:openView={(e) => openView(e.detail.path, e.detail.title)}
			/>
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
						title="Content"
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
