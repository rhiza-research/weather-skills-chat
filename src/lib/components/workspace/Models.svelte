<script lang="ts">
	import { marked } from 'marked';

	import { toast } from 'svelte-sonner';
	import fileSaver from 'file-saver';
	const { saveAs } = fileSaver;

	import { onMount, getContext } from 'svelte';
	import { goto } from '$app/navigation';
	const i18n = getContext('i18n');

	import {
		WEBUI_NAME,
		config,
		models as _models,
		organizations,
		activeOrganizationId,
		settings,
		user
	} from '$lib/stores';
	import {
		createNewModel,
		deleteModelById,
		getModelById,
		getModels as getWorkspaceModels,
		setModelEnabled,
		setModelEnabledByDefault,
		toggleModelById,
		updateModelById
	} from '$lib/apis/models';

	import { getModels } from '$lib/apis';

	import EllipsisHorizontal from '../icons/EllipsisHorizontal.svelte';
	import ModelMenu from './Models/ModelMenu.svelte';
	import ModelDeleteConfirmDialog from '../common/ConfirmDialog.svelte';
	import Tooltip from '../common/Tooltip.svelte';
	import GarbageBin from '../icons/GarbageBin.svelte';
	import Search from '../icons/Search.svelte';
	import Plus from '../icons/Plus.svelte';
	import Switch from '../common/Switch.svelte';
	import Spinner from '../common/Spinner.svelte';
	import { capitalizeFirstLetter } from '$lib/utils';
	import {
		canAddKind,
		canManageCatalogItem,
		isCatalogEnabled,
		isOrgAdminRole,
		isPublicItem
	} from '$lib/utils/catalog';

	export let catalog: 'public' | 'org' = 'org';

	let shiftKey = false;

	let importFiles;
	let modelsImportInputElement: HTMLInputElement;
	let loaded = false;

	let models = [];

	let filteredModels = [];
	let selectedModel = null;

	let showModelDeleteConfirm = false;

	$: basePath = catalog === 'public' ? '/admin' : '/workspace';
	$: currentOrg = ($organizations ?? []).find((org) => org.id === $activeOrganizationId);
	$: orgAdmin = catalog === 'public' || isOrgAdminRole(currentOrg);
	$: canCreate = catalog === 'public' || (orgAdmin && canAddKind(currentOrg, 'models'));
	$: showOrgSection = catalog === 'org' && canAddKind(currentOrg, 'models');
	$: orgName = currentOrg?.name || $i18n.t('Organization');

	$: if (models) {
		filteredModels = models.filter(
			(m) => searchValue === '' || m.name.toLowerCase().includes(searchValue.toLowerCase())
		);
	}

	$: publicModels = filteredModels.filter((m) => isPublicItem(m));
	$: orgModels = filteredModels.filter((m) => !isPublicItem(m));
	$: sectionModels = catalog === 'public' ? filteredModels : orgModels;

	let searchValue = '';

	const canManage = (model) => canManageCatalogItem(catalog, model, currentOrg);

	const deleteModelHandler = async (model) => {
		const res = await deleteModelById(localStorage.token, model.id).catch((e) => {
			toast.error(`${e}`);
			return null;
		});

		if (res) {
			toast.success($i18n.t(`Deleted {{name}}`, { name: model.id }));
		}

		await _models.set(
			await getModels(
				localStorage.token,
				$config?.features?.enable_direct_connections && ($settings?.directConnections ?? null)
			)
		);
		models = await getWorkspaceModels(localStorage.token);
	};

	const prepareModelClone = (source) => {
		const { user: _user, user_id, created_at, updated_at, ...rest } = source;
		return {
			...rest,
			access_control: {},
			is_active: rest.is_active ?? true
		};
	};

	const cloneModelHandler = async (model) => {
		const source = await getModelById(localStorage.token, model.id).catch((error) => {
			toast.error(`${error}`);
			return null;
		});

		if (!source) {
			toast.error($i18n.t('Could not load model to clone'));
			return;
		}

		const clone = prepareModelClone(source);
		sessionStorage.model = JSON.stringify({
			...clone,
			id: `${source.id}-clone`,
			name: `${source.name} (Clone)`
		});
		goto(`${basePath}/models/create`);
	};

	const hideModelHandler = async (model) => {
		let info = model.info;

		if (!info) {
			info = {
				id: model.id,
				name: model.name,
				meta: {
					suggestion_prompts: null
				},
				params: {}
			};
		}

		info.meta = {
			...info.meta,
			hidden: !(info?.meta?.hidden ?? false)
		};

		const res = await updateModelById(localStorage.token, info.id, info);

		if (res) {
			toast.success(
				$i18n.t(`Model {{name}} is now {{status}}`, {
					name: info.id,
					status: info.meta.hidden ? 'hidden' : 'visible'
				})
			);
		}

		await _models.set(
			await getModels(
				localStorage.token,
				$config?.features?.enable_direct_connections && ($settings?.directConnections ?? null)
			)
		);
		models = await getWorkspaceModels(localStorage.token);
	};

	const downloadModels = async (models) => {
		let blob = new Blob([JSON.stringify(models)], {
			type: 'application/json'
		});
		saveAs(blob, `models-export-${Date.now()}.json`);
	};

	const exportModelHandler = async (model) => {
		let blob = new Blob([JSON.stringify([model])], {
			type: 'application/json'
		});
		saveAs(blob, `${model.id}-${Date.now()}.json`);
	};

	const setEnabledHandler = async (model, enabled) => {
		const previous = !!model.enabled;
		model.enabled = enabled;
		models = models;
		const res = await setModelEnabled(localStorage.token, model.id, enabled).catch((e) => {
			toast.error(`${e}`);
			return null;
		});
		if (!res) {
			model.enabled = previous;
			models = models;
			return;
		}
		await _models.set(
			await getModels(
				localStorage.token,
				$config?.features?.enable_direct_connections && ($settings?.directConnections ?? null)
			)
		);
		models = await getWorkspaceModels(localStorage.token);
	};

	const setEnabledByDefaultHandler = async (model, enabledByDefault) => {
		const previous = model.enabled_by_default !== false;
		model.enabled_by_default = enabledByDefault;
		models = models;
		const res = await setModelEnabledByDefault(
			localStorage.token,
			model.id,
			enabledByDefault
		).catch((e) => {
			toast.error(`${e}`);
			return null;
		});
		if (!res) {
			model.enabled_by_default = previous;
			models = models;
			return;
		}
		models = await getWorkspaceModels(localStorage.token);
	};

	onMount(async () => {
		models = await getWorkspaceModels(localStorage.token);
		loaded = true;

		const onKeyDown = (event) => {
			if (event.key === 'Shift') {
				shiftKey = true;
			}
		};

		const onKeyUp = (event) => {
			if (event.key === 'Shift') {
				shiftKey = false;
			}
		};

		const onBlur = () => {
			shiftKey = false;
		};

		window.addEventListener('keydown', onKeyDown);
		window.addEventListener('keyup', onKeyUp);
		window.addEventListener('blur-sm', onBlur);

		return () => {
			window.removeEventListener('keydown', onKeyDown);
			window.removeEventListener('keyup', onKeyUp);
			window.removeEventListener('blur-sm', onBlur);
		};
	});
</script>

<svelte:head>
	<title>
		{$i18n.t('Models')} | {$WEBUI_NAME}
	</title>
</svelte:head>

{#if loaded}
	<ModelDeleteConfirmDialog
		bind:show={showModelDeleteConfirm}
		on:confirm={() => {
			deleteModelHandler(selectedModel);
		}}
	/>

	<div class="flex flex-col gap-1 my-1.5">
		<div class="flex justify-between items-center">
			<div class="flex items-center md:self-center text-xl font-medium px-0.5">
				{$i18n.t('Models')}
				<div class="flex self-center w-[1px] h-6 mx-2.5 bg-gray-50 dark:bg-gray-850" />
				<span class="text-lg font-medium text-gray-500 dark:text-gray-300"
					>{filteredModels.length}</span
				>
			</div>
		</div>

		<div class=" flex flex-1 items-center w-full space-x-2">
			<div class="flex flex-1 items-center">
				<div class=" self-center ml-1 mr-3">
					<Search className="size-3.5" />
				</div>
				<input
					class=" w-full text-sm py-1 rounded-r-xl outline-hidden bg-transparent"
					bind:value={searchValue}
					placeholder={$i18n.t('Search Models')}
				/>
			</div>

			{#if canCreate}
				<div>
					<a
						class=" px-2 py-2 rounded-xl hover:bg-gray-700/10 dark:hover:bg-gray-100/10 dark:text-gray-300 dark:hover:text-white transition font-medium text-sm flex items-center space-x-1"
						href={`${basePath}/models/create`}
					>
						<Plus className="size-3.5" />
					</a>
				</div>
			{/if}
		</div>
	</div>

	{#if catalog === 'org'}
		<div class="mt-4 mb-1 text-sm font-medium text-gray-500 dark:text-gray-400">
			{$i18n.t('Models from catalog')}
		</div>
		{#if publicModels.length === 0}
			<div class="text-xs text-gray-500 py-3">{$i18n.t('No models')}</div>
		{/if}
		<div class=" my-2 mb-5 gap-2 grid lg:grid-cols-2 xl:grid-cols-3">
			{#each publicModels as model}
				{@const manage = canManage(model)}
				{@const usable = isCatalogEnabled(model)}
				<div
					class=" flex flex-col w-full px-3 py-2 rounded-xl transition {usable
						? 'cursor-pointer dark:hover:bg-white/5 hover:bg-black/5'
						: 'cursor-default'}"
					id="model-item-{model.id}"
				>
					<div class="flex gap-4 mt-0.5 mb-0.5">
						<div class=" w-[44px]">
							<div class=" rounded-full object-cover {usable ? '' : 'opacity-50'} ">
								<img
									src={model?.meta?.profile_image_url ?? '/static/favicon.png'}
									alt="modelfile profile"
									class=" rounded-full w-full h-auto object-cover"
								/>
							</div>
						</div>

						<svelte:element
							this={usable ? 'a' : 'div'}
							class=" flex flex-1 w-full {usable ? 'cursor-pointer' : 'cursor-default'}"
							href={usable ? `/?models=${encodeURIComponent(model.id)}` : undefined}
						>
							<div class=" flex-1 self-center {usable ? '' : 'text-gray-500'}">
								<Tooltip
									content={marked.parse(model?.meta?.description ?? model.id)}
									className=" w-fit"
									placement="top-start"
								>
									<div class=" font-semibold line-clamp-1">{model.name}</div>
								</Tooltip>
								<div class="flex gap-1 text-xs overflow-hidden">
									<div class="line-clamp-1">
										{#if (model?.meta?.description ?? '').trim()}
											{model?.meta?.description}
										{:else}
											{model.id}
										{/if}
									</div>
								</div>
							</div>
						</svelte:element>
					</div>

					<div class="flex justify-end items-center -mb-0.5 px-0.5">
						<div class="flex flex-row gap-0.5 items-center">
							{#if canCreate}
								<ModelMenu
									user={$user}
									{model}
									cloneHandler={() => {
										cloneModelHandler(model);
									}}
									exportHandler={() => {
										exportModelHandler(model);
									}}
									hideHandler={() => {
										hideModelHandler(model);
									}}
									deleteHandler={() => {}}
									onClose={() => {}}
								>
									<button
										class="self-center w-fit text-sm p-1.5 dark:text-gray-300 dark:hover:text-white hover:bg-black/5 dark:hover:bg-white/5 rounded-xl"
										type="button"
									>
										<EllipsisHorizontal className="size-5" />
									</button>
								</ModelMenu>
							{/if}

							<div class="ml-1">
								<Tooltip content={model.enabled ? $i18n.t('Enabled') : $i18n.t('Disabled')}>
									{#if orgAdmin}
										<Switch
											state={!!model.enabled}
											on:change={async (e) => {
												const next = !!e.detail;
												if (next === !!model.enabled) return;
												await setEnabledHandler(model, next);
											}}
										/>
									{:else}
										<span class="text-xs text-gray-500"
											>{model.enabled ? $i18n.t('Enabled') : $i18n.t('Disabled')}</span
										>
									{/if}
								</Tooltip>
							</div>
						</div>
					</div>
				</div>
			{/each}
		</div>

		{#if showOrgSection}
			<div class="mt-4 mb-1 text-sm font-medium text-gray-500 dark:text-gray-400">
				{$i18n.t('{{name}} Models', { name: orgName })}
			</div>
			{#if sectionModels.length === 0}
				<div class="text-xs text-gray-500 py-3">{$i18n.t('No models')}</div>
			{/if}
		{/if}
	{/if}

	{#if catalog === 'public' || showOrgSection}
	<div class=" my-2 mb-5 gap-2 grid lg:grid-cols-2 xl:grid-cols-3" id="model-list">
		{#each sectionModels as model}
			{@const manage = canManage(model)}
			<div
				class=" flex flex-col cursor-pointer w-full px-3 py-2 dark:hover:bg-white/5 hover:bg-black/5 rounded-xl transition"
				id="model-item-{model.id}"
			>
				<div class="flex gap-4 mt-0.5 mb-0.5">
					<div class=" w-[44px]">
						<div
							class=" rounded-full object-cover {model.is_active
								? ''
								: 'opacity-50 dark:opacity-50'} "
						>
							<img
								src={model?.meta?.profile_image_url ?? '/static/favicon.png'}
								alt="modelfile profile"
								class=" rounded-full w-full h-auto object-cover"
							/>
						</div>
					</div>

					<a
						class=" flex flex-1 cursor-pointer w-full"
						href={`/?models=${encodeURIComponent(model.id)}`}
					>
						<div class=" flex-1 self-center {model.is_active ? '' : 'text-gray-500'}">
							<Tooltip
								content={marked.parse(model?.meta?.description ?? model.id)}
								className=" w-fit"
								placement="top-start"
							>
								<div class=" font-semibold line-clamp-1">{model.name}</div>
							</Tooltip>

							<div class="flex gap-1 text-xs overflow-hidden">
								<div class="line-clamp-1">
									{#if (model?.meta?.description ?? '').trim()}
										{model?.meta?.description}
									{:else}
										{model.id}
									{/if}
								</div>
							</div>
						</div>
					</a>
				</div>

				<div
					class="flex items-center -mb-0.5 px-0.5 {catalog === 'public'
						? 'justify-between'
						: 'justify-end'}"
				>
					{#if catalog === 'public'}
						<div class=" text-xs mt-0.5">
							<Tooltip
								content={model?.user?.email ?? $i18n.t('Deleted User')}
								className="flex shrink-0"
								placement="top-start"
							>
								<div class="shrink-0 text-gray-500">
									{$i18n.t('By {{name}}', {
										name: capitalizeFirstLetter(
											model?.user?.name ?? model?.user?.email ?? $i18n.t('Deleted User')
										)
									})}
								</div>
							</Tooltip>
						</div>
					{/if}

					<div class="flex flex-row gap-0.5 items-center">
						{#if shiftKey && manage}
							<Tooltip content={$i18n.t('Delete')}>
								<button
									class="self-center w-fit text-sm px-2 py-2 dark:text-gray-300 dark:hover:text-white hover:bg-black/5 dark:hover:bg-white/5 rounded-xl"
									type="button"
									on:click={() => {
										deleteModelHandler(model);
									}}
								>
									<GarbageBin />
								</button>
							</Tooltip>
						{:else}
							{#if manage}
								<a
									class="self-center w-fit text-sm px-2 py-2 dark:text-gray-300 dark:hover:text-white hover:bg-black/5 dark:hover:bg-white/5 rounded-xl"
									type="button"
									href={`${basePath}/models/edit?id=${encodeURIComponent(model.id)}`}
								>
									<svg
										xmlns="http://www.w3.org/2000/svg"
										fill="none"
										viewBox="0 0 24 24"
										stroke-width="1.5"
										stroke="currentColor"
										class="w-4 h-4"
									>
										<path
											stroke-linecap="round"
											stroke-linejoin="round"
											d="m16.862 4.487 1.687-1.688a1.875 1.875 0 1 1 2.652 2.652L6.832 19.82a4.5 4.5 0 0 1-1.897 1.13l-2.685.8.8-2.685a4.5 4.5 0 0 1 1.13-1.897L16.863 4.487Zm0 0L19.5 7.125"
										/>
									</svg>
								</a>
							{/if}

							{#if manage || canCreate}
								<ModelMenu
									user={$user}
									{model}
									cloneHandler={() => {
										cloneModelHandler(model);
									}}
									exportHandler={() => {
										exportModelHandler(model);
									}}
									hideHandler={() => {
										hideModelHandler(model);
									}}
									deleteHandler={() => {
										selectedModel = model;
										showModelDeleteConfirm = true;
									}}
									onClose={() => {}}
								>
									<button
										class="self-center w-fit text-sm p-1.5 dark:text-gray-300 dark:hover:text-white hover:bg-black/5 dark:hover:bg-white/5 rounded-xl"
										type="button"
									>
										<EllipsisHorizontal className="size-5" />
									</button>
								</ModelMenu>
							{/if}

							{#if manage}
								<div class="ml-1 flex items-center gap-2">
									{#if catalog === 'public'}
										<Tooltip content={$i18n.t('Enabled by default')}>
											<div class="flex items-center gap-1">
												<span
													class="text-[10px] leading-none text-gray-500 max-w-[4.5rem] text-right {!model.is_active
														? 'opacity-40'
														: ''}"
													>{$i18n.t('Enabled by default')}</span
												>
												<Switch
													state={model.enabled_by_default !== false}
													disabled={!model.is_active}
													on:change={async (e) => {
														if (!model.is_active) return;
														const next = !!e.detail;
														if (next === (model.enabled_by_default !== false)) return;
														await setEnabledByDefaultHandler(model, next);
													}}
												/>
											</div>
										</Tooltip>
										<Tooltip
											content={model.is_active
												? $i18n.t('In catalog')
												: $i18n.t('Not in catalog')}
										>
											<div class="flex items-center gap-1">
												<span class="text-[10px] leading-none text-gray-500"
													>{$i18n.t('In catalog')}</span
												>
												<Switch
													bind:state={model.is_active}
													on:change={async () => {
														await toggleModelById(localStorage.token, model.id);
														models = await getWorkspaceModels(localStorage.token);
														_models.set(
															await getModels(
																localStorage.token,
																$config?.features?.enable_direct_connections &&
																	($settings?.directConnections ?? null)
															)
														);
													}}
												/>
											</div>
										</Tooltip>
									{:else}
										<Tooltip content={model.is_active ? $i18n.t('Enabled') : $i18n.t('Disabled')}>
											<Switch
												bind:state={model.is_active}
												on:change={async (e) => {
													toggleModelById(localStorage.token, model.id);
													_models.set(
														await getModels(
															localStorage.token,
															$config?.features?.enable_direct_connections &&
																($settings?.directConnections ?? null)
														)
													);
												}}
											/>
										</Tooltip>
									{/if}
								</div>
							{/if}
						{/if}
					</div>
				</div>
			</div>
		{/each}
	</div>
	{/if}

	{#if catalog === 'public'}
		<div class=" flex justify-end w-full mb-3">
			<div class="flex space-x-1">
				<input
					id="models-import-input"
					bind:this={modelsImportInputElement}
					bind:files={importFiles}
					type="file"
					accept=".json"
					hidden
					on:change={() => {
						let reader = new FileReader();
						reader.onload = async (event) => {
							let savedModels = JSON.parse(event.target.result);

							for (const model of savedModels) {
								if (model?.info ?? false) {
									if ($_models.find((m) => m.id === model.id)) {
										await updateModelById(localStorage.token, model.id, model.info).catch(() => {
											return null;
										});
									} else {
										await createNewModel(localStorage.token, model.info).catch(() => {
											return null;
										});
									}
								} else {
									if (model?.id && model?.name) {
										await createNewModel(localStorage.token, model).catch(() => {
											return null;
										});
									}
								}
							}

							await _models.set(
								await getModels(
									localStorage.token,
									$config?.features?.enable_direct_connections &&
										($settings?.directConnections ?? null)
								)
							);
							models = await getWorkspaceModels(localStorage.token);
						};

						reader.readAsText(importFiles[0]);
					}}
				/>

				<button
					class="flex text-xs items-center space-x-1 px-3 py-1.5 rounded-xl bg-gray-50 hover:bg-gray-100 dark:bg-gray-800 dark:hover:bg-gray-700 dark:text-gray-200 transition"
					on:click={() => {
						modelsImportInputElement.click();
					}}
				>
					<div class=" self-center mr-2 font-medium line-clamp-1">{$i18n.t('Import Models')}</div>
				</button>

				{#if models.length}
					<button
						class="flex text-xs items-center space-x-1 px-3 py-1.5 rounded-xl bg-gray-50 hover:bg-gray-100 dark:bg-gray-800 dark:hover:bg-gray-700 dark:text-gray-200 transition"
						on:click={async () => {
							downloadModels(models);
						}}
					>
						<div class=" self-center mr-2 font-medium line-clamp-1">
							{$i18n.t('Export Models')}
						</div>
					</button>
				{/if}
			</div>
		</div>
	{/if}

{:else}
	<div class="w-full h-full flex justify-center items-center">
		<Spinner />
	</div>
{/if}
