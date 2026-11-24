<script lang="ts">
	import ArrowDownTraySolid from '$lib/components/icons/ArrowDownTraySolid.svelte';
	import { toast } from 'svelte-sonner';

	import { onMount, getContext, createEventDispatcher } from 'svelte';

	const dispatch = createEventDispatcher();

	import {
		getQuerySettings,
		updateQuerySettings,
		resetVectorDB,
		getEmbeddingConfig,
		updateEmbeddingConfig,
		getRerankingConfig,
		updateRerankingConfig,
		getRAGConfig,
		updateRAGConfig
	} from '$lib/apis/retrieval';

	import { reindexKnowledgeFiles } from '$lib/apis/knowledge';
	import { deleteAllFiles } from '$lib/apis/files';

	import ResetUploadDirConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import ResetVectorDBConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import ReindexKnowledgeFilesConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import SensitiveInput from '$lib/components/common/SensitiveInput.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Switch from '$lib/components/common/Switch.svelte';
	import Textarea from '$lib/components/common/Textarea.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';

	const i18n = getContext('i18n');

	let updateEmbeddingModelLoading = false;
	let updateRerankingModelLoading = false;

	let showResetConfirm = false;
	let showResetUploadDirConfirm = false;
	let showReindexConfirm = false;

	let embeddingEngine = '';
	let embeddingModel = '';
	let embeddingBatchSize = 1;
	let rerankingModel = '';

	let OpenAIUrl = '';
	let OpenAIKey = '';

	let OllamaUrl = '';
	let OllamaKey = '';

	let querySettings = {
		template: '',
		r: 0.0,
		k: 4,
		k_reranker: 4,
		hybrid: false
	};

	let RAGConfig = null;

	const embeddingModelUpdateHandler = async () => {
		if (embeddingEngine === '' && embeddingModel.split('/').length - 1 > 1) {
			toast.error(
				$i18n.t(
					'Model filesystem path detected. Model shortname is required for update, cannot continue.'
				)
			);
			return;
		}
		if (embeddingEngine === 'ollama' && embeddingModel === '') {
			toast.error(
				$i18n.t(
					'Model filesystem path detected. Model shortname is required for update, cannot continue.'
				)
			);
			return;
		}

		if (embeddingEngine === 'openai' && embeddingModel === '') {
			toast.error(
				$i18n.t(
					'Model filesystem path detected. Model shortname is required for update, cannot continue.'
				)
			);
			return;
		}

		if ((embeddingEngine === 'openai' && OpenAIKey === '') || OpenAIUrl === '') {
			toast.error($i18n.t('OpenAI URL/Key required.'));
			return;
		}

		console.log('Update embedding model attempt:', embeddingModel);

		updateEmbeddingModelLoading = true;
		const res = await updateEmbeddingConfig(localStorage.token, {
			embedding_engine: embeddingEngine,
			embedding_model: embeddingModel,
			embedding_batch_size: embeddingBatchSize,
			ollama_config: {
				key: OllamaKey,
				url: OllamaUrl
			},
			openai_config: {
				key: OpenAIKey,
				url: OpenAIUrl
			}
		}).catch(async (error) => {
			toast.error(`${error}`);
			await setEmbeddingConfig();
			return null;
		});
		updateEmbeddingModelLoading = false;

		if (res) {
			console.log('embeddingModelUpdateHandler:', res);
			if (res.status === true) {
				toast.success($i18n.t('Embedding model set to "{{embedding_model}}"', res), {
					duration: 1000 * 10
				});
			}
		}
	};

	const rerankingModelUpdateHandler = async () => {
		console.log('Update reranking model attempt:', rerankingModel);

		updateRerankingModelLoading = true;
		const res = await updateRerankingConfig(localStorage.token, {
			reranking_model: rerankingModel
		}).catch(async (error) => {
			toast.error(`${error}`);
			await setRerankingConfig();
			return null;
		});
		updateRerankingModelLoading = false;

		if (res) {
			console.log('rerankingModelUpdateHandler:', res);
			if (res.status === true) {
				if (rerankingModel === '') {
					toast.success($i18n.t('Reranking model disabled', res), {
						duration: 1000 * 10
					});
				} else {
					toast.success($i18n.t('Reranking model set to "{{reranking_model}}"', res), {
						duration: 1000 * 10
					});
				}
			}
		}
	};

	const submitHandler = async () => {
		if (RAGConfig.CONTENT_EXTRACTION_ENGINE === 'tika' && RAGConfig.TIKA_SERVER_URL === '') {
			toast.error($i18n.t('Tika Server URL required.'));
			return;
		}
		if (RAGConfig.CONTENT_EXTRACTION_ENGINE === 'docling' && RAGConfig.DOCLING_SERVER_URL === '') {
			toast.error($i18n.t('Docling Server URL required.'));
			return;
		}

		if (
			RAGConfig.CONTENT_EXTRACTION_ENGINE === 'document_intelligence' &&
			(RAGConfig.DOCUMENT_INTELLIGENCE_ENDPOINT === '' ||
				RAGConfig.DOCUMENT_INTELLIGENCE_KEY === '')
		) {
			toast.error($i18n.t('Document Intelligence endpoint and key required.'));
			return;
		}
		if (
			RAGConfig.CONTENT_EXTRACTION_ENGINE === 'mistral_ocr' &&
			RAGConfig.MISTRAL_OCR_API_KEY === ''
		) {
			toast.error($i18n.t('Mistral OCR API Key required.'));
			return;
		}

		if (!RAGConfig.BYPASS_EMBEDDING_AND_RETRIEVAL) {
			await embeddingModelUpdateHandler();

			if (RAGConfig.ENABLE_RAG_HYBRID_SEARCH) {
				await rerankingModelUpdateHandler();
			}
		}

		const res = await updateRAGConfig(localStorage.token, RAGConfig);
		dispatch('save');
	};

	const setEmbeddingConfig = async () => {
		const embeddingConfig = await getEmbeddingConfig(localStorage.token);

		if (embeddingConfig) {
			embeddingEngine = embeddingConfig.embedding_engine;
			embeddingModel = embeddingConfig.embedding_model;
			embeddingBatchSize = embeddingConfig.embedding_batch_size ?? 1;

			OpenAIKey = embeddingConfig.openai_config.key;
			OpenAIUrl = embeddingConfig.openai_config.url;

			OllamaKey = embeddingConfig.ollama_config.key;
			OllamaUrl = embeddingConfig.ollama_config.url;
		}
	};

	const setRerankingConfig = async () => {
		const rerankingConfig = await getRerankingConfig(localStorage.token);

		if (rerankingConfig) {
			rerankingModel = rerankingConfig.reranking_model;
		}
	};

	onMount(async () => {
		await setEmbeddingConfig();
		await setRerankingConfig();

		RAGConfig = await getRAGConfig(localStorage.token);
	});
	import SettingRow from '$lib/components/common/SettingRow.svelte';
</script>

<ResetUploadDirConfirmDialog
	bind:show={showResetUploadDirConfirm}
	on:confirm={async () => {
		const res = await deleteAllFiles(localStorage.token).catch((error) => {
			toast.error(`${error}`);
			return null;
		});

		if (res) {
			toast.success($i18n.t('Success'));
		}
	}}
/>

<ResetVectorDBConfirmDialog
	bind:show={showResetConfirm}
	on:confirm={() => {
		const res = resetVectorDB(localStorage.token).catch((error) => {
			toast.error(`${error}`);
			return null;
		});

		if (res) {
			toast.success($i18n.t('Success'));
		}
	}}
/>

<ReindexKnowledgeFilesConfirmDialog
	bind:show={showReindexConfirm}
	on:confirm={async () => {
		const res = await reindexKnowledgeFiles(localStorage.token).catch((error) => {
			toast.error(`${error}`);
			return null;
		});

		if (res) {
			toast.success($i18n.t('Success'));
		}
	}}
/>

<form
	class="flex flex-col h-full justify-between space-y-3 text-sm"
	on:submit|preventDefault={() => {
		submitHandler();
	}}
>
	{#if RAGConfig}
		<div class=" space-y-2.5 overflow-y-scroll scrollbar-hidden h-full pr-1.5">
			<div class="">
				<div class="mb-3">
					<h3 class="section-title">{$i18n.t('General')}</h3>

					<hr class="border-line my-2" />

					<div class="mb-2.5 flex flex-col w-full justify-between">
						<SettingRow label={$i18n.t('Content Extraction Engine')}>
							<div class="">
								<select
									class="field-select"
									bind:value={RAGConfig.CONTENT_EXTRACTION_ENGINE}
								>
									<option value="">{$i18n.t('Default')}</option>
									<option value="tika">{$i18n.t('Tika')}</option>
									<option value="docling">{$i18n.t('Docling')}</option>
									<option value="document_intelligence">{$i18n.t('Document Intelligence')}</option>
									<option value="mistral_ocr">{$i18n.t('Mistral OCR')}</option>
								</select>
							</div>
						</SettingRow>

						{#if RAGConfig.CONTENT_EXTRACTION_ENGINE === ''}
							<div class="flex w-full mt-1">
								<div class="flex-1 flex justify-between">
									<div class=" self-center text-xs font-medium">
										{$i18n.t('PDF Extract Images (OCR)')}
									</div>
									<div class="flex items-center relative">
										<Switch bind:state={RAGConfig.PDF_EXTRACT_IMAGES} />
									</div>
								</div>
							</div>
						{:else if RAGConfig.CONTENT_EXTRACTION_ENGINE === 'tika'}
							<div class="flex w-full mt-1">
								<div class="flex-1 mr-2">
									<input
										class="w-full bg-transparent outline-hidden flex-1 text-sm"
										placeholder={$i18n.t('Enter Tika Server URL')}
										bind:value={RAGConfig.TIKA_SERVER_URL}
									/>
								</div>
							</div>
						{:else if RAGConfig.CONTENT_EXTRACTION_ENGINE === 'docling'}
							<div class="flex w-full mt-1">
								<input
									class="w-full bg-transparent outline-hidden flex-1 text-sm"
									placeholder={$i18n.t('Enter Docling Server URL')}
									bind:value={RAGConfig.DOCLING_SERVER_URL}
								/>
							</div>
						{:else if RAGConfig.CONTENT_EXTRACTION_ENGINE === 'document_intelligence'}
							<div class="my-0.5 flex gap-2 pr-2">
								<input
									class="w-full bg-transparent outline-hidden flex-1 text-sm"
									placeholder={$i18n.t('Enter Document Intelligence Endpoint')}
									bind:value={RAGConfig.DOCUMENT_INTELLIGENCE_ENDPOINT}
								/>
								<SensitiveInput
									placeholder={$i18n.t('Enter Document Intelligence Key')}
									bind:value={RAGConfig.DOCUMENT_INTELLIGENCE_KEY}
								/>
							</div>
						{:else if RAGConfig.CONTENT_EXTRACTION_ENGINE === 'mistral_ocr'}
							<div class="my-0.5 flex gap-2 pr-2">
								<SensitiveInput
									placeholder={$i18n.t('Enter Mistral API Key')}
									bind:value={RAGConfig.MISTRAL_OCR_API_KEY}
								/>
							</div>
						{/if}
					</div>

					<div class="  mb-2.5 flex w-full justify-between">
						<div class=" self-center text-xs font-medium">
							<Tooltip content={$i18n.t('Full Context Mode')} placement="top-start">
								{$i18n.t('Bypass Embedding and Retrieval')}
							</Tooltip>
						</div>
						<div class="flex items-center relative">
							<Tooltip
								content={RAGConfig.BYPASS_EMBEDDING_AND_RETRIEVAL
									? $i18n.t(
											'Inject the entire content as context for comprehensive processing, this is recommended for complex queries.'
										)
									: $i18n.t(
											'Default to segmented retrieval for focused and relevant content extraction, this is recommended for most cases.'
										)}
							>
								<Switch bind:state={RAGConfig.BYPASS_EMBEDDING_AND_RETRIEVAL} />
							</Tooltip>
						</div>
					</div>

					{#if !RAGConfig.BYPASS_EMBEDDING_AND_RETRIEVAL}
						<SettingRow label={$i18n.t('Text Splitter')}>
							<div class="flex items-center relative">
								<select
									class="field-select"
									bind:value={RAGConfig.TEXT_SPLITTER}
								>
									<option value="">{$i18n.t('Default')} ({$i18n.t('Character')})</option>
									<option value="token">{$i18n.t('Token')} ({$i18n.t('Tiktoken')})</option>
								</select>
							</div>
						</SettingRow>

						<div class="  mb-2.5 flex w-full justify-between">
							<div class=" flex gap-1.5 w-full">
								<div class="  w-full justify-between">
									<div class="self-center text-xs font-medium min-w-fit mb-1">
										{$i18n.t('Chunk Size')}
									</div>
									<div class="self-center">
										<input
											class="field"
											type="number"
											placeholder={$i18n.t('Enter Chunk Size')}
											bind:value={RAGConfig.CHUNK_SIZE}
											autocomplete="off"
											min="0"
										/>
									</div>
								</div>

								<div class="w-full">
									<div class=" self-center text-xs font-medium min-w-fit mb-1">
										{$i18n.t('Chunk Overlap')}
									</div>

									<div class="self-center">
										<input
											class="field"
											type="number"
											placeholder={$i18n.t('Enter Chunk Overlap')}
											bind:value={RAGConfig.CHUNK_OVERLAP}
											autocomplete="off"
											min="0"
										/>
									</div>
								</div>
							</div>
						</div>
					{/if}
				</div>

				{#if !RAGConfig.BYPASS_EMBEDDING_AND_RETRIEVAL}
					<div class="mb-3">
						<h3 class="section-title">{$i18n.t('Embedding')}</h3>

						<hr class="border-line my-2" />

						<div class="  mb-2.5 flex flex-col w-full justify-between">
							<SettingRow label={$i18n.t('Embedding Model Engine')}>
								<div class="flex items-center relative">
									<select
										class="field-select"
										bind:value={embeddingEngine}
										placeholder={$i18n.t('Select an embedding model engine')}
										on:change={(e) => {
											if (e.target.value === 'ollama') {
												embeddingModel = '';
											} else if (e.target.value === 'openai') {
												embeddingModel = 'text-embedding-3-small';
											} else if (e.target.value === '') {
												embeddingModel = 'sentence-transformers/all-MiniLM-L6-v2';
											}
										}}
									>
										<option value="">{$i18n.t('Default (SentenceTransformers)')}</option>
										<option value="ollama">{$i18n.t('Ollama')}</option>
										<option value="openai">{$i18n.t('OpenAI')}</option>
									</select>
								</div>
							</SettingRow>

							{#if embeddingEngine === 'openai'}
								<div class="my-0.5 flex gap-2 pr-2">
									<input
										class="w-full bg-transparent outline-hidden flex-1 text-sm"
										placeholder={$i18n.t('API Base URL')}
										bind:value={OpenAIUrl}
										required
									/>

									<SensitiveInput placeholder={$i18n.t('API Key')} bind:value={OpenAIKey} />
								</div>
							{:else if embeddingEngine === 'ollama'}
								<div class="my-0.5 flex gap-2 pr-2">
									<input
										class="w-full bg-transparent outline-hidden flex-1 text-sm"
										placeholder={$i18n.t('API Base URL')}
										bind:value={OllamaUrl}
										required
									/>

									<SensitiveInput
										placeholder={$i18n.t('API Key')}
										bind:value={OllamaKey}
										required={false}
									/>
								</div>
							{/if}
						</div>

						<div class="  mb-2.5 flex flex-col w-full">
							<div class=" mb-1 text-xs font-medium">{$i18n.t('Embedding Model')}</div>

							<div class="">
								{#if embeddingEngine === 'ollama'}
									<div class="flex w-full">
										<div class="flex-1 mr-2">
											<input
												class="w-full bg-transparent outline-hidden flex-1 text-sm"
												bind:value={embeddingModel}
												placeholder={$i18n.t('Set embedding model')}
												required
											/>
										</div>
									</div>
								{:else}
									<div class="flex w-full">
										<div class="flex-1 mr-2">
											<input
												class="w-full bg-transparent outline-hidden flex-1 text-sm"
												placeholder={$i18n.t('Set embedding model (e.g. {{model}})', {
													model: embeddingModel.slice(-40)
												})}
												bind:value={embeddingModel}
											/>
										</div>

										{#if embeddingEngine === ''}
											<button
												class="px-2.5 bg-transparent text-strong dark:bg-transparent rounded-lg transition"
												on:click={() => {
													embeddingModelUpdateHandler();
												}}
												disabled={updateEmbeddingModelLoading}
											>
												{#if updateEmbeddingModelLoading}
													<div class="self-center">
														<svg
															class=" size-4"
															viewBox="0 0 24 24"
															fill="currentColor"
															xmlns="http://www.w3.org/2000/svg"
														>
															<style>
																.spinner_ajPY {
																	transform-origin: center;
																	animation: spinner_AtaB 0.75s infinite linear;
																}

																@keyframes spinner_AtaB {
																	100% {
																		transform: rotate(360deg);
																	}
																}
															</style>
															<path
																d="M12,1A11,11,0,1,0,23,12,11,11,0,0,0,12,1Zm0,19a8,8,0,1,1,8-8A8,8,0,0,1,12,20Z"
																opacity=".25"
															/>
															<path
																d="M10.14,1.16a11,11,0,0,0-9,8.92A1.59,1.59,0,0,0,2.46,12,1.52,1.52,0,0,0,4.11,10.7a8,8,0,0,1,6.66-6.61A1.42,1.42,0,0,0,12,2.69h0A1.57,1.57,0,0,0,10.14,1.16Z"
																class="spinner_ajPY"
															/>
														</svg>
													</div>
												{:else}
													<ArrowDownTraySolid className="size-4" />
												{/if}
											</button>
										{/if}
									</div>
								{/if}
							</div>

							<div class="mt-1 mb-1 text-xs text-muted">
								{$i18n.t(
									'Warning: If you update or change your embedding model, you will need to re-import all documents.'
								)}
							</div>
						</div>

						{#if embeddingEngine === 'ollama' || embeddingEngine === 'openai'}
							<SettingRow label={$i18n.t('Embedding Batch Size')}>
								<div class="">
									<input
										bind:value={embeddingBatchSize}
										type="number"
										class=" bg-transparent text-center w-14 outline-none"
										min="-2"
										max="16000"
										step="1"
									/>
								</div>
							</SettingRow>
						{/if}
					</div>

					<div class="mb-3">
						<h3 class="section-title">{$i18n.t('Retrieval')}</h3>

						<hr class="border-line my-2" />

						<SettingRow label={$i18n.t('Full Context Mode')}>
							<div class="flex items-center relative">
								<Tooltip
									content={RAGConfig.RAG_FULL_CONTEXT
										? $i18n.t(
												'Inject the entire content as context for comprehensive processing, this is recommended for complex queries.'
											)
										: $i18n.t(
												'Default to segmented retrieval for focused and relevant content extraction, this is recommended for most cases.'
											)}
								>
									<Switch bind:state={RAGConfig.RAG_FULL_CONTEXT} />
								</Tooltip>
							</div>
						</SettingRow>

						{#if !RAGConfig.RAG_FULL_CONTEXT}
							<SettingRow label={$i18n.t('Hybrid Search')}>
								<div class="flex items-center relative">
									<Switch
										bind:state={RAGConfig.ENABLE_RAG_HYBRID_SEARCH}
										on:change={() => {
											submitHandler();
										}}
									/>
								</div>
							</SettingRow>

							{#if RAGConfig.ENABLE_RAG_HYBRID_SEARCH === true}
								<div class="  mb-2.5 flex flex-col w-full">
									<div class=" mb-1 text-xs font-medium">{$i18n.t('Reranking Model')}</div>

									<div class="">
										<div class="flex w-full">
											<div class="flex-1 mr-2">
												<input
													class="w-full bg-transparent outline-hidden flex-1 text-sm"
													placeholder={$i18n.t('Set reranking model (e.g. {{model}})', {
														model: 'BAAI/bge-reranker-v2-m3'
													})}
													bind:value={rerankingModel}
												/>
											</div>
											<button
												class="px-2.5 bg-transparent text-strong dark:bg-transparent rounded-lg transition"
												on:click={() => {
													rerankingModelUpdateHandler();
												}}
												disabled={updateRerankingModelLoading}
											>
												{#if updateRerankingModelLoading}
													<div class="self-center">
														<svg
															class=" size-4"
															viewBox="0 0 24 24"
															fill="currentColor"
															xmlns="http://www.w3.org/2000/svg"
														>
															<style>
																.spinner_ajPY {
																	transform-origin: center;
																	animation: spinner_AtaB 0.75s infinite linear;
																}

																@keyframes spinner_AtaB {
																	100% {
																		transform: rotate(360deg);
																	}
																}
															</style>
															<path
																d="M12,1A11,11,0,1,0,23,12,11,11,0,0,0,12,1Zm0,19a8,8,0,1,1,8-8A8,8,0,0,1,12,20Z"
																opacity=".25"
															/>
															<path
																d="M10.14,1.16a11,11,0,0,0-9,8.92A1.59,1.59,0,0,0,2.46,12,1.52,1.52,0,0,0,4.11,10.7a8,8,0,0,1,6.66-6.61A1.42,1.42,0,0,0,12,2.69h0A1.57,1.57,0,0,0,10.14,1.16Z"
																class="spinner_ajPY"
															/>
														</svg>
													</div>
												{:else}
													<ArrowDownTraySolid className="size-4" />
												{/if}
											</button>
										</div>
									</div>
								</div>
							{/if}

							<SettingRow label={$i18n.t('Top K')}>
								<div class="flex items-center relative">
									<input
										class="w-full bg-transparent outline-hidden flex-1 text-sm"
										type="number"
										placeholder={$i18n.t('Enter Top K')}
										bind:value={RAGConfig.TOP_K}
										autocomplete="off"
										min="0"
									/>
								</div>
							</SettingRow>

							{#if RAGConfig.ENABLE_RAG_HYBRID_SEARCH === true}
								<SettingRow label={$i18n.t('Top K Reranker')}>
									<div class="flex items-center relative">
										<input
											class="w-full bg-transparent outline-hidden flex-1 text-sm"
											type="number"
											placeholder={$i18n.t('Enter Top K Reranker')}
											bind:value={RAGConfig.TOP_K_RERANKER}
											autocomplete="off"
											min="0"
										/>
									</div>
								</SettingRow>
							{/if}

							{#if RAGConfig.ENABLE_RAG_HYBRID_SEARCH === true}
								<div class="  mb-2.5 flex flex-col w-full justify-between">
									<SettingRow label={$i18n.t('Relevance Threshold')}>
										<div class="flex items-center relative">
											<input
												class="w-full bg-transparent outline-hidden flex-1 text-sm"
												type="number"
												step="0.01"
												placeholder={$i18n.t('Enter Score')}
												bind:value={RAGConfig.RELEVANCE_THRESHOLD}
												autocomplete="off"
												min="0.0"
												title={$i18n.t(
													'The score should be a value between 0.0 (0%) and 1.0 (100%).'
												)}
											/>
										</div>
									</SettingRow>
									<div class="mt-1 text-xs text-muted">
										{$i18n.t(
											'Note: If you set a minimum score, the search will only return documents with a score greater than or equal to the minimum score.'
										)}
									</div>
								</div>
							{/if}
						{/if}

						<div class="  mb-2.5 flex flex-col w-full justify-between">
							<div class=" mb-1 text-xs font-medium">{$i18n.t('RAG Template')}</div>
							<div class="flex w-full items-center relative">
								<Tooltip
									content={$i18n.t(
										'Leave empty to use the default prompt, or enter a custom prompt'
									)}
									placement="top-start"
									className="w-full"
								>
									<Textarea
										bind:value={RAGConfig.RAG_TEMPLATE}
										placeholder={$i18n.t(
											'Leave empty to use the default prompt, or enter a custom prompt'
										)}
									/>
								</Tooltip>
							</div>
						</div>
					</div>
				{/if}

				<div class="mb-3">
					<h3 class="section-title">{$i18n.t('Files')}</h3>

					<hr class="border-line my-2" />

					<SettingRow label={$i18n.t('Max Upload Size')}>
						<div class="flex items-center relative">
							<Tooltip
								content={$i18n.t(
									'The maximum file size in MB. If the file size exceeds this limit, the file will not be uploaded.'
								)}
								placement="top-start"
							>
								<input
									class="w-full bg-transparent outline-hidden flex-1 text-sm"
									type="number"
									placeholder={$i18n.t('Leave empty for unlimited')}
									bind:value={RAGConfig.FILE_MAX_SIZE}
									autocomplete="off"
									min="0"
								/>
							</Tooltip>
						</div>
					</SettingRow>

					<SettingRow label={$i18n.t('Max Upload Count')}>
						<div class="flex items-center relative">
							<Tooltip
								content={$i18n.t(
									'The maximum number of files that can be used at once in chat. If the number of files exceeds this limit, the files will not be uploaded.'
								)}
								placement="top-start"
							>
								<input
									class="w-full bg-transparent outline-hidden flex-1 text-sm"
									type="number"
									placeholder={$i18n.t('Leave empty for unlimited')}
									bind:value={RAGConfig.FILE_MAX_COUNT}
									autocomplete="off"
									min="0"
								/>
							</Tooltip>
						</div>
					</SettingRow>
				</div>

				<div class="mb-3">
					<h3 class="section-title">{$i18n.t('Integration')}</h3>

					<hr class="border-line my-2" />

					<SettingRow label={$i18n.t('Google Drive')}>
						<div class="flex items-center relative">
							<Switch bind:state={RAGConfig.ENABLE_GOOGLE_DRIVE_INTEGRATION} />
						</div>
					</SettingRow>

					<SettingRow label={$i18n.t('OneDrive')}>
						<div class="flex items-center relative">
							<Switch bind:state={RAGConfig.ENABLE_ONEDRIVE_INTEGRATION} />
						</div>
					</SettingRow>
				</div>

				<div class="mb-3">
					<h3 class="section-title">{$i18n.t('Danger Zone')}</h3>

					<hr class="border-line my-2" />

					<SettingRow label={$i18n.t('Reset Upload Directory')}>
						<div class="flex items-center relative">
							<button
								class="text-xs"
								on:click={() => {
									showResetUploadDirConfirm = true;
								}}
							>
								{$i18n.t('Reset')}
							</button>
						</div>
					</SettingRow>

					<SettingRow label={$i18n.t('Reset Vector Storage/Knowledge')}>
						<div class="flex items-center relative">
							<button
								class="text-xs"
								on:click={() => {
									showResetConfirm = true;
								}}
							>
								{$i18n.t('Reset')}
							</button>
						</div>
					</SettingRow>
					<SettingRow label={$i18n.t('Reindex Knowledge Base Vectors')}>
						<div class="flex items-center relative">
							<button
								class="text-xs"
								on:click={() => {
									showReindexConfirm = true;
								}}
							>
								{$i18n.t('Reindex')}
							</button>
						</div>
					</SettingRow>
				</div>
			</div>
		</div>
		<div class="flex justify-end pt-3 text-sm font-medium">
			<button
				class="btn-primary"
				type="submit"
			>
				{$i18n.t('Save')}
			</button>
		</div>
	{:else}
		<div class="flex items-center justify-center h-full">
			<Spinner />
		</div>
	{/if}
</form>
