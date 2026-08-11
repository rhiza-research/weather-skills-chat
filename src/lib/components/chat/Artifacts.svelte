<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { onMount, onDestroy, getContext, createEventDispatcher } from 'svelte';
	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher();

	import { chatId, settings, showArtifacts, showControls } from '$lib/stores';
	import {
		createZarrView,
		getArtifactContentUrl,
		getChatArtifacts,
		getZarrMeta,
		getZarrRenderUrl,
		uploadChatArtifact
	} from '$lib/apis/artifacts';
	import XMark from '../icons/XMark.svelte';
	import { copyToClipboard, createMessagesList } from '$lib/utils';
	import ArrowsPointingOut from '../icons/ArrowsPointingOut.svelte';
	import Tooltip from '../common/Tooltip.svelte';
	import SvgPanZoom from '../common/SVGPanZoom.svelte';
	import ArrowLeft from '../icons/ArrowLeft.svelte';

	export let overlay = false;
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
	let showViewForm = false;
	let viewForm = { zarr: '', title: '', variable: '', style: 'heatmap', colormap: 'viridis' };
	let zarrMeta = null;

	$: zarrStores = files.filter((file) => file.kind === 'zarr');
	$: orphanViews = files.filter(
		(file) =>
			file.kind === 'zarr_view' && !zarrStores.some((store) => store.path === file.zarr)
	);
	$: otherFiles = files.filter(
		(file) => file.kind !== 'zarr' && file.kind !== 'zarr_view'
	);
	const viewsFor = (zarrPath) =>
		files.filter((file) => file.kind === 'zarr_view' && file.zarr === zarrPath);

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
			return;
		}
		previewUrl = URL.createObjectURL(await res.blob());
	};

	const loadFiles = async () => {
		if (!$chatId || $chatId === 'local') {
			files = [];
			return;
		}
		try {
			files = await getChatArtifacts(localStorage.token, $chatId);
		} catch (e) {
			files = [];
		}
	};

	$: if ($chatId) {
		loadFiles();
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
						const content = block.replace(/<\/?html>/gi, ''); // Remove <html> tags
						htmlContent += content + '\n';
					});
				}
				if (inlineCss) {
					inlineCss.forEach((block) => {
						const content = block.replace(/<\/?style>/gi, ''); // Remove <style> tags
						cssContent += content + '\n';
					});
				}
				if (inlineJs) {
					inlineJs.forEach((block) => {
						const content = block.replace(/<\/?script>/gi, ''); // Remove <script> tags
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
									background-color: white; /* Ensure the iframe has a white background */
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
				} else {
					// Check for SVG content
					for (const block of codeBlocks) {
						if (block.lang === 'svg' || (block.lang === 'xml' && block.code.includes('<svg'))) {
							contents = [...contents, { type: 'svg', content: block.code }];
						}
					}
				}
			}
		});

		if (contents.length === 0 && files.length === 0) {
			// Keep the panel open so filesystem artifacts can still be managed.
		}

		selectedContentIdx = contents ? contents.length - 1 : 0;
	};

	function navigateContent(direction: 'prev' | 'next') {
		console.log(selectedContentIdx);

		selectedContentIdx =
			direction === 'prev'
				? Math.max(selectedContentIdx - 1, 0)
				: Math.min(selectedContentIdx + 1, contents.length - 1);

		console.log(selectedContentIdx);
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
					} else {
						console.log('External navigation blocked:', url.href);
					}
				}
			},
			true
		);

		// Cancel drag when hovering over iframe
		iframeElement.contentWindow.addEventListener('mouseenter', function (e) {
			e.preventDefault();
			iframeElement.contentWindow.addEventListener('dragstart', (event) => {
				event.preventDefault();
			});
		});
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

	onMount(() => {});
	onDestroy(revokePreview);
</script>

<div class=" w-full h-full relative flex flex-col bg-gray-50 dark:bg-gray-850">
	<div class="w-full h-full flex flex-col flex-1 relative overflow-y-auto">
		<div class="p-3 border-b border-gray-100 dark:border-gray-800">
			<div class="flex items-center justify-between mb-2">
				<div class="text-xs font-medium">{$i18n.t('Files')}</div>
				<label class="text-xs text-gray-500 cursor-pointer">
					{$i18n.t('Upload')}
					<input
						type="file"
						class="hidden"
						on:change={async (e) => {
							const file = e.currentTarget.files?.[0];
							if (!file || !$chatId) return;
							await uploadChatArtifact(localStorage.token, $chatId, file.name, file);
							await loadFiles();
							e.currentTarget.value = '';
						}}
					/>
				</label>
			</div>
			<div class="flex flex-col gap-1 max-h-48 overflow-y-auto">
				{#each zarrStores as store}
					<div class="flex items-center justify-between text-xs px-1 py-0.5">
						<div class="truncate flex items-center gap-1">
							<span>{store.path}</span>
							<span class="text-gray-400">zarr</span>
						</div>
						<button
							class="underline shrink-0"
							on:click={async () => {
								viewForm.zarr = store.path;
								showViewForm = true;
								selectedImage = null;
								zarrMeta = await getZarrMeta(localStorage.token, $chatId, store.path).catch(
									() => null
								);
							}}>{$i18n.t('New view')}</button
						>
					</div>
					{#each viewsFor(store.path) as file}
						<div class="flex items-center justify-between text-xs px-1 py-0.5 pl-4">
							<div class="truncate flex items-center gap-1">
								{#if file.missing_zarr}
									<span class="text-red-500" title={$i18n.t('Referenced zarr is missing')}>!</span>
								{/if}
								<span>{file.title || file.path}</span>
								<span class="text-gray-400">view</span>
							</div>
							{#if !file.missing_zarr}
								<button
									class="underline shrink-0"
									on:click={async () => {
										selectedView = file.path;
										selectedImage = null;
										await loadPreview(getZarrRenderUrl($chatId, file.path));
									}}>{$i18n.t('View')}</button
								>
							{/if}
						</div>
					{/each}
				{/each}
				{#each orphanViews as file}
					<div class="flex items-center justify-between text-xs px-1 py-0.5">
						<div class="truncate flex items-center gap-1">
							<span class="text-red-500" title={$i18n.t('Referenced zarr is missing')}>!</span>
							<span>{file.title || file.path}</span>
							<span class="text-gray-400">view</span>
						</div>
					</div>
				{/each}
				{#each otherFiles as file}
					<div class="flex items-center justify-between text-xs px-1 py-0.5">
						<div class="truncate flex items-center gap-1">
							<span>{file.path}</span>
							<span class="text-gray-400">{file.kind}</span>
						</div>
						<div class="flex gap-1 shrink-0">
							{#if file.kind === 'image'}
								<button
									class="underline"
									on:click={async () => {
										selectedImage = file.path;
										selectedView = null;
										await loadPreview(getArtifactContentUrl($chatId, file.path));
									}}>{$i18n.t('Preview')}</button
								>
							{:else if !file.is_dir}
								<a
									class="underline"
									href={getArtifactContentUrl($chatId, file.path)}
									target="_blank">{$i18n.t('Download')}</a
								>
							{/if}
						</div>
					</div>
				{/each}
				{#if files.length === 0}
					<div class="text-[11px] text-gray-400">{$i18n.t('No files in this chat yet.')}</div>
				{/if}
			</div>
			{#if showViewForm}
				<form
					class="mt-2 flex flex-col gap-1"
					on:submit|preventDefault={async () => {
						await createZarrView(localStorage.token, $chatId, viewForm);
						showViewForm = false;
						await loadFiles();
					}}
				>
					<input
						class="rounded bg-white dark:bg-gray-900 px-2 py-1 text-xs"
						placeholder={$i18n.t('View title')}
						bind:value={viewForm.title}
					/>
					<select class="rounded bg-white dark:bg-gray-900 px-2 py-1 text-xs" bind:value={viewForm.variable}>
						<option value="">{$i18n.t('First variable')}</option>
						{#if zarrMeta}
							{#each Object.keys(zarrMeta.variables || {}) as name}
								<option value={name}>{name}</option>
							{/each}
						{/if}
					</select>
					<select class="rounded bg-white dark:bg-gray-900 px-2 py-1 text-xs" bind:value={viewForm.style}>
						<option value="heatmap">heatmap</option>
						<option value="timeseries">timeseries</option>
					</select>
					<input
						class="rounded bg-white dark:bg-gray-900 px-2 py-1 text-xs"
						placeholder={$i18n.t('Colormap (viridis)')}
						bind:value={viewForm.colormap}
					/>
					<div class="flex gap-1">
						<button class="text-xs underline" type="submit">{$i18n.t('Save view')}</button>
						<button class="text-xs text-gray-400" type="button" on:click={() => (showViewForm = false)}
							>{$i18n.t('Cancel')}</button
						>
					</div>
				</form>
			{/if}
			{#if previewUrl}
				<img
					class="mt-2 w-full rounded border border-gray-100 dark:border-gray-800"
					src={previewUrl}
					alt={selectedView || selectedImage}
				/>
			{/if}
		</div>
		{#if contents.length > 0}
			<div
				class="pointer-events-auto z-20 flex justify-between items-center p-2.5 font-primar text-gray-900 dark:text-white"
			>
				<button
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
					class="self-center pointer-events-auto p-1 rounded-full bg-white dark:bg-gray-850"
					on:click={() => {
						dispatch('close');
						showControls.set(false);
						showArtifacts.set(false);
					}}
				>
					<XMark className="size-3.5 text-gray-900 dark:text-white" />
				</button>
			</div>
		{/if}

		{#if overlay}
			<div class=" absolute top-0 left-0 right-0 bottom-0 z-10"></div>
		{/if}

		<div class="flex-1 w-full h-full">
			<div class=" h-full flex flex-col">
				{#if contents.length > 0}
					<div class="max-w-full w-full h-full">
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
				{:else}
					<div class="m-auto font-medium text-xs text-gray-900 dark:text-white">
						{$i18n.t('No HTML, CSS, or JavaScript content found.')}
					</div>
				{/if}
			</div>
		</div>
	</div>
</div>
