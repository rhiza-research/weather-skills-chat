<script lang="ts">
	import { onMount, getContext } from 'svelte';
	import { toast } from 'svelte-sonner';
	import {
		tools as toolsStore,
		organizations,
		activeOrganizationId
	} from '$lib/stores';
	import { getTools } from '$lib/apis/tools';
	import {
		deleteSkillPack,
		getSkillPacks,
		installSkillPack,
		setSkillEnabledByDefault,
		setSkillPackEnabled,
		setSkillPackEnabledByDefault,
		toggleSkillActive,
		toggleSkillPackActive,
		updateSkillPack,
		updateSkillEnabled
	} from '$lib/apis/skills';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import ChevronRight from '$lib/components/icons/ChevronRight.svelte';
	import Switch from '$lib/components/common/Switch.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import {
		canAddKind,
		canManageCatalogItem,
		isCatalogEnabled,
		isOrgAdminRole,
		isPublicItem
	} from '$lib/utils/catalog';

	export let catalog: 'public' | 'org' = 'org';

	const i18n = getContext('i18n');

	let loaded = false;
	let busy = false;
	let packs = [];
	let gitUrl = '';
	let gitRef = 'main';
	let enabledByDefault = true;
	let deletePackId = '';
	let showDeleteConfirm = false;

	$: currentOrg = ($organizations ?? []).find((org) => org.id === $activeOrganizationId);
	$: orgAdmin = catalog === 'public' || isOrgAdminRole(currentOrg);
	$: canCreate = catalog === 'public' || (orgAdmin && canAddKind(currentOrg, 'skills'));
	$: showOrgSection = catalog === 'org' && canAddKind(currentOrg, 'skills');
	$: orgName = currentOrg?.name || $i18n.t('Organization');
	$: publicPacks = packs.filter((pack) => isPublicItem(pack));
	$: orgPacks = packs.filter((pack) => !isPublicItem(pack));
	$: sectionPacks = catalog === 'public' ? packs : orgPacks;

	const canManage = (pack) => canManageCatalogItem(catalog, pack, currentOrg);

	const shortSha = (sha: string) => (sha ? sha.slice(0, 7) : '');

	const packUsable = (pack) =>
		isPublicItem(pack) ? isCatalogEnabled(pack) : pack?.is_active !== false;

	const skillEnabled = (skill) => skill?.enabled !== false;

	const refresh = async () => {
		packs =
			(await getSkillPacks(localStorage.token).catch((error) => {
				toast.error(`${error}`);
				return [];
			})) || [];
	};

	const refreshTools = async () => {
		try {
			await toolsStore.set(await getTools(localStorage.token));
		} catch (_) {}
	};

	const applyPack = (updated) => {
		if (!updated) return false;
		const idx = packs.findIndex((p) => p.id === updated.id);
		if (idx >= 0) {
			packs[idx] = updated;
			packs = packs;
		}
		return true;
	};

	const installHandler = async () => {
		if (busy) return;
		if (!gitUrl.trim()) {
			toast.error('Git URL is required');
			return;
		}
		busy = true;
		const pack = await installSkillPack(
			localStorage.token,
			gitUrl.trim(),
			(gitRef || 'main').trim(),
			catalog === 'public' ? enabledByDefault : true
		).catch((error) => {
			toast.error(`${error}`);
			return null;
		});
		busy = false;
		if (pack) {
			toast.success(`Installed ${pack.skills?.length || 0} skill(s) from ${pack.git_ref}`);
			gitUrl = '';
			gitRef = 'main';
			enabledByDefault = true;
			await refresh();
			await refreshTools();
		}
	};

	const updateHandler = async (pack) => {
		if (busy) return;
		busy = true;
		const updated = await updateSkillPack(localStorage.token, pack.id).catch((error) => {
			toast.error(`${error}`);
			return null;
		});
		busy = false;
		if (updated) {
			toast.success(`Updated to ${shortSha(updated.commit_sha)} on ${updated.git_ref}`);
			await refresh();
			await refreshTools();
		}
	};

	const setEnabledHandler = async (pack, enabled) => {
		const previous = !!pack.enabled;
		pack.enabled = enabled;
		packs = packs;
		const updated = await setSkillPackEnabled(localStorage.token, pack.id, enabled).catch(
			(error) => {
				toast.error(`${error}`);
				return null;
			}
		);
		if (!applyPack(updated)) {
			pack.enabled = previous;
			packs = packs;
			return;
		}
		await refreshTools();
	};

	const setPackEnabledByDefaultHandler = async (pack, enabled) => {
		const previous = pack.enabled_by_default !== false;
		pack.enabled_by_default = enabled;
		packs = packs;
		const updated = await setSkillPackEnabledByDefault(
			localStorage.token,
			pack.id,
			enabled
		).catch((error) => {
			toast.error(`${error}`);
			return null;
		});
		if (!applyPack(updated)) {
			pack.enabled_by_default = previous;
			packs = packs;
			return;
		}
		await refreshTools();
	};

	const togglePackActiveHandler = async (pack) => {
		const previous = pack.is_active !== false;
		const updated = await toggleSkillPackActive(localStorage.token, pack.id).catch((error) => {
			toast.error(`${error}`);
			return null;
		});
		if (!applyPack(updated)) {
			pack.is_active = previous;
			packs = packs;
			return;
		}
		await refreshTools();
	};

	const deleteHandler = async () => {
		if (!deletePackId || busy) return;
		busy = true;
		const ok = await deleteSkillPack(localStorage.token, deletePackId).catch((error) => {
			toast.error(`${error}`);
			return null;
		});
		busy = false;
		showDeleteConfirm = false;
		deletePackId = '';
		if (ok) {
			toast.success('Skill pack removed');
			await refresh();
			await refreshTools();
		}
	};

	const toggleSkillEnabled = async (pack, skill, enabled) => {
		if (!pack?.id || !skill?.tool_id) return;
		const previous = skillEnabled(skill);
		skill.enabled = enabled;
		packs = packs;

		const updated = await updateSkillEnabled(
			localStorage.token,
			pack.id,
			skill.tool_id,
			enabled
		).catch((error) => {
			toast.error(`${error}`);
			return null;
		});

		if (!applyPack(updated)) {
			skill.enabled = previous;
			packs = packs;
			return;
		}
		await refreshTools();
	};

	const setSkillEnabledByDefaultHandler = async (pack, skill, enabled) => {
		if (!pack?.id || !skill?.tool_id) return;
		const previous = skill.enabled_by_default !== false;
		skill.enabled_by_default = enabled;
		packs = packs;
		const updated = await setSkillEnabledByDefault(
			localStorage.token,
			pack.id,
			skill.tool_id,
			enabled
		).catch((error) => {
			toast.error(`${error}`);
			return null;
		});
		if (!applyPack(updated)) {
			skill.enabled_by_default = previous;
			packs = packs;
			return;
		}
		await refreshTools();
	};

	const toggleSkillActiveHandler = async (pack, skill) => {
		if (!pack?.id || !skill?.tool_id) return;
		const previous = skill.is_active !== false;
		const updated = await toggleSkillActive(localStorage.token, pack.id, skill.tool_id).catch(
			(error) => {
				toast.error(`${error}`);
				return null;
			}
		);
		if (!applyPack(updated)) {
			skill.is_active = previous;
			packs = packs;
			return;
		}
		await refreshTools();
	};

	onMount(async () => {
		await refresh();
		loaded = true;
	});
</script>

<ConfirmDialog
	bind:show={showDeleteConfirm}
	onConfirm={deleteHandler}
	title={$i18n.t('Delete')}
	message="Remove this skill pack and its linked tools?"
/>

{#if loaded}
	<div class="mb-3">
		<div class="text-lg font-medium mb-1">Skills</div>
		<div class="text-sm text-gray-500 dark:text-gray-400 mb-4">
			{#if catalog === 'public'}
				Install Agent Skills into the public catalog. Organizations can then enable or disable each
				pack and skill. Skills run like tools in chat.
			{:else}
				Platform skill packs can be turned on or off for this organization. Organization packs are
				only visible here.
			{/if}
		</div>

		{#if canCreate}
			<div
				class="flex flex-col gap-4 mb-6 p-4 rounded-xl bg-gray-50 dark:bg-gray-850 border border-gray-100 dark:border-gray-800"
			>
				<div class="flex flex-col md:flex-row gap-2">
					<input
						class="flex-1 w-full text-sm rounded-lg py-2 px-3 bg-transparent outline-hidden"
						placeholder="https://github.com/org/weather-skills.git"
						bind:value={gitUrl}
						disabled={busy}
					/>
					<input
						class="md:w-48 w-full text-sm rounded-lg py-2 px-3 bg-transparent outline-hidden border border-gray-200 dark:border-gray-700"
						placeholder="branch / tag / sha"
						bind:value={gitRef}
						disabled={busy}
					/>
					<button
						class="px-3.5 py-2 text-sm rounded-lg bg-gray-900 text-white dark:bg-white dark:text-gray-900 disabled:opacity-50"
						disabled={busy}
						on:click={installHandler}
					>
						Install
					</button>
				</div>
				{#if catalog === 'public'}
					<label class="flex items-center gap-3 pt-1">
						<Switch bind:state={enabledByDefault} />
						<span class="text-sm text-gray-600 dark:text-gray-300"
							>{$i18n.t('Enabled by default')}</span
						>
					</label>
				{/if}
			</div>
		{/if}

		{#if busy}
			<div class="flex justify-center py-4"><Spinner /></div>
		{/if}

		{#if catalog === 'org'}
			<div class="mt-4 mb-1 text-sm font-medium text-gray-500 dark:text-gray-400">
				{$i18n.t('Skills from catalog')}
			</div>
			{#if publicPacks.length === 0}
				<div class="text-sm text-gray-500 dark:text-gray-400 py-4">No platform skill packs.</div>
			{:else}
				<div class="flex flex-col gap-3 mb-6">
					{#each publicPacks as pack (pack.id)}
						<details
							class="skill-pack rounded-xl border border-gray-100 dark:border-gray-800 bg-white dark:bg-gray-900 {packUsable(
								pack
							)
								? ''
								: 'opacity-60'}"
						>
							<summary
								class="flex flex-wrap items-start justify-between gap-2 p-3.5 cursor-pointer list-none"
							>
								<div class="flex min-w-0 flex-1 items-start gap-2">
									<span class="skill-pack-chevron mt-0.5 shrink-0 text-gray-500">
										<ChevronRight className="size-4" />
									</span>
									<div class="min-w-0">
										<div class="font-medium truncate">{pack.name}</div>
										<div class="text-xs text-gray-500 dark:text-gray-400 break-all">
											{pack.git_url}
										</div>
										<div class="text-xs text-gray-500 dark:text-gray-400 mt-1">
											ref <span class="font-mono">{pack.git_ref}</span>
											{#if pack.commit_sha}
												· <span class="font-mono">{shortSha(pack.commit_sha)}</span>
											{/if}
											· {(pack.skills || []).length} skill(s)
										</div>
									</div>
								</div>
								<!-- svelte-ignore a11y-click-events-have-key-events -->
								<!-- svelte-ignore a11y-no-static-element-interactions -->
								<div
									class="flex flex-wrap gap-1.5 items-center"
									on:click|stopPropagation
									on:mousedown|stopPropagation
								>
									{#if orgAdmin}
										<Tooltip content={pack.enabled ? $i18n.t('Enabled') : $i18n.t('Disabled')}>
											<Switch
												state={!!pack.enabled}
												on:change={(e) => {
													const next = !!e.detail;
													if (next === !!pack.enabled) return;
													setEnabledHandler(pack, next);
												}}
											/>
										</Tooltip>
									{:else}
										<span class="text-xs text-gray-500"
											>{pack.enabled ? $i18n.t('Enabled') : $i18n.t('Disabled')}</span
										>
									{/if}
								</div>
							</summary>
							<div class="px-3.5 pb-3.5 border-t border-gray-100 dark:border-gray-800">
								{#if (pack.skills || []).length}
									<ul class="mt-3 divide-y divide-gray-100 dark:divide-gray-800">
										{#each pack.skills as skill (skill.tool_id || skill.name)}
											<li class="py-2.5 text-sm flex items-start justify-between gap-3">
												<div class="min-w-0 flex-1">
													<span
														class="font-medium {skillEnabled(skill)
															? ''
															: 'text-gray-400 dark:text-gray-500'}"
													>
														{skill.name}
													</span>
													{#if skill.version}
														<span class="text-xs text-gray-500">v{skill.version}</span>
													{/if}
													{#if !skillEnabled(skill)}
														<span class="text-xs text-gray-400 ml-1">{$i18n.t('Disabled')}</span>
													{/if}
													{#if skill.description}
														<div class="text-xs text-gray-500 dark:text-gray-400 line-clamp-2">
															{skill.description}
														</div>
													{/if}
												</div>
												{#if skill.tool_id && orgAdmin}
													<!-- svelte-ignore a11y-click-events-have-key-events -->
													<!-- svelte-ignore a11y-no-static-element-interactions -->
													<div
														class="shrink-0 pt-0.5"
														on:click|stopPropagation
														on:mousedown|stopPropagation
													>
														<Tooltip
															content={skillEnabled(skill)
																? $i18n.t('Enabled')
																: $i18n.t('Disabled')}
														>
															<Switch
																state={skillEnabled(skill)}
																on:change={(e) => {
																	const next = !!e.detail;
																	if (next === skillEnabled(skill)) return;
																	toggleSkillEnabled(pack, skill, next);
																}}
															/>
														</Tooltip>
													</div>
												{/if}
											</li>
										{/each}
									</ul>
								{/if}
							</div>
						</details>
					{/each}
				</div>
			{/if}

			{#if showOrgSection}
				<div class="mt-4 mb-1 text-sm font-medium text-gray-500 dark:text-gray-400">
					{$i18n.t('{{name}} Skills', { name: orgName })}
				</div>
			{/if}
		{/if}

		{#if catalog === 'public' || showOrgSection}
		{#if sectionPacks.length === 0}
			<div class="text-sm text-gray-500 dark:text-gray-400 py-6 text-center">
				No skill packs installed yet.
			</div>
		{:else}
			<div class="flex flex-col gap-3">
				{#each sectionPacks as pack (pack.id)}
					<details
						class="skill-pack rounded-xl border border-gray-100 dark:border-gray-800 bg-white dark:bg-gray-900 {catalog ===
							'org' && !packUsable(pack)
							? 'opacity-60'
							: ''}"
					>
						<summary
							class="flex flex-wrap items-start justify-between gap-2 p-3.5 cursor-pointer list-none"
						>
							<div class="flex min-w-0 flex-1 items-start gap-2">
								<span class="skill-pack-chevron mt-0.5 shrink-0 text-gray-500">
									<ChevronRight className="size-4" />
								</span>
								<div class="min-w-0">
									<div class="font-medium truncate">{pack.name}</div>
									<div class="text-xs text-gray-500 dark:text-gray-400 break-all">
										{pack.git_url}
									</div>
									<div class="text-xs text-gray-500 dark:text-gray-400 mt-1">
										ref <span class="font-mono">{pack.git_ref}</span>
										{#if pack.commit_sha}
											· <span class="font-mono">{shortSha(pack.commit_sha)}</span>
										{/if}
										· {(pack.skills || []).length} skill(s)
									</div>
								</div>
							</div>
							<!-- svelte-ignore a11y-click-events-have-key-events -->
							<!-- svelte-ignore a11y-no-static-element-interactions -->
							<div
								class="flex flex-wrap gap-2 items-center"
								on:click|stopPropagation
								on:mousedown|stopPropagation
							>
								{#if catalog === 'public' && canManage(pack)}
									<Tooltip content={$i18n.t('Enabled by default')}>
										<div class="flex items-center gap-1.5">
											<span
												class="text-[10px] leading-none text-gray-500 max-w-[4.5rem] text-right {pack.is_active ===
												false
													? 'opacity-40'
													: ''}"
												>{$i18n.t('Enabled by default')}</span
											>
											<Switch
												state={pack.enabled_by_default !== false}
												disabled={pack.is_active === false}
												on:change={(e) => {
													if (pack.is_active === false) return;
													const next = !!e.detail;
													if (next === (pack.enabled_by_default !== false)) return;
													setPackEnabledByDefaultHandler(pack, next);
												}}
											/>
										</div>
									</Tooltip>
									<Tooltip
										content={pack.is_active !== false
											? $i18n.t('In catalog')
											: $i18n.t('Not in catalog')}
									>
										<div class="flex items-center gap-1.5">
											<span class="text-[10px] leading-none text-gray-500"
												>{$i18n.t('In catalog')}</span
											>
											<Switch
												state={pack.is_active !== false}
												on:change={(e) => {
													const next = !!e.detail;
													if (next === (pack.is_active !== false)) return;
													togglePackActiveHandler(pack);
												}}
											/>
										</div>
									</Tooltip>
								{:else if catalog === 'org' && orgAdmin}
									<Tooltip content={packUsable(pack) ? $i18n.t('Enabled') : $i18n.t('Disabled')}>
										<Switch
											state={packUsable(pack)}
											on:change={(e) => {
												const next = !!e.detail;
												if (next === packUsable(pack)) return;
												togglePackActiveHandler(pack);
											}}
										/>
									</Tooltip>
								{/if}
								{#if canManage(pack)}
									<button
										type="button"
										class="text-xs px-2.5 py-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-850"
										disabled={busy}
										on:click|stopPropagation={() => updateHandler(pack)}
									>
										Update
									</button>
									<button
										type="button"
										class="text-xs px-2.5 py-1.5 rounded-lg text-red-600 hover:bg-red-50 dark:hover:bg-red-950"
										disabled={busy}
										on:click|stopPropagation={() => {
											deletePackId = pack.id;
											showDeleteConfirm = true;
										}}
									>
										Remove
									</button>
								{/if}
							</div>
						</summary>

						<div class="px-3.5 pb-3.5 border-t border-gray-100 dark:border-gray-800">
							{#if (pack.skills || []).length}
								<ul class="mt-3 divide-y divide-gray-100 dark:divide-gray-800">
									{#each pack.skills as skill (skill.tool_id || skill.name)}
										<li class="py-2.5 text-sm flex items-start justify-between gap-3">
											<div class="min-w-0 flex-1">
												<span
													class="font-medium {skillEnabled(skill) && skill.is_active !== false
														? ''
														: 'text-gray-400 dark:text-gray-500'}"
												>
													{skill.name}
												</span>
												{#if skill.version}
													<span class="text-xs text-gray-500">v{skill.version}</span>
												{/if}
												{#if catalog === 'public' && skill.is_active === false}
													<span class="text-xs text-gray-400 ml-1">{$i18n.t('Not in catalog')}</span>
												{:else if !skillEnabled(skill)}
													<span class="text-xs text-gray-400 ml-1"
														>{catalog === 'public'
															? 'off by default'
															: $i18n.t('Disabled')}</span
													>
												{/if}
												{#if skill.description}
													<div class="text-xs text-gray-500 dark:text-gray-400 line-clamp-2">
														{skill.description}
													</div>
												{/if}
											</div>
											{#if skill.tool_id && (catalog === 'public' ? canManage(pack) : orgAdmin)}
												<!-- svelte-ignore a11y-click-events-have-key-events -->
												<!-- svelte-ignore a11y-no-static-element-interactions -->
												<div
													class="shrink-0 pt-0.5 flex flex-wrap items-center gap-2"
													on:click|stopPropagation
													on:mousedown|stopPropagation
												>
													{#if catalog === 'public'}
														<Tooltip content={$i18n.t('Enabled by default')}>
															<div class="flex items-center gap-1.5">
																<span
																	class="text-[10px] leading-none text-gray-500 max-w-[4.5rem] text-right {skill.is_active ===
																	false
																		? 'opacity-40'
																		: ''}"
																	>{$i18n.t('Enabled by default')}</span
																>
																<Switch
																	state={skill.enabled_by_default !== false}
																	disabled={skill.is_active === false}
																	on:change={(e) => {
																		if (skill.is_active === false) return;
																		const next = !!e.detail;
																		if (next === (skill.enabled_by_default !== false)) return;
																		setSkillEnabledByDefaultHandler(pack, skill, next);
																	}}
																/>
															</div>
														</Tooltip>
														<Tooltip
															content={skill.is_active !== false
																? $i18n.t('In catalog')
																: $i18n.t('Not in catalog')}
														>
															<div class="flex items-center gap-1.5">
																<span class="text-[10px] leading-none text-gray-500"
																	>{$i18n.t('In catalog')}</span
																>
																<Switch
																	state={skill.is_active !== false}
																	on:change={(e) => {
																		const next = !!e.detail;
																		if (next === (skill.is_active !== false)) return;
																		toggleSkillActiveHandler(pack, skill);
																	}}
																/>
															</div>
														</Tooltip>
													{:else}
														<Tooltip
															content={skillEnabled(skill)
																? $i18n.t('Enabled')
																: $i18n.t('Disabled')}
														>
															<Switch
																state={skillEnabled(skill)}
																on:change={(e) => {
																	const next = !!e.detail;
																	if (next === skillEnabled(skill)) return;
																	toggleSkillEnabled(pack, skill, next);
																}}
															/>
														</Tooltip>
													{/if}
												</div>
											{/if}
										</li>
									{/each}
								</ul>
							{:else}
								<div class="mt-3 text-xs text-gray-500 dark:text-gray-400">
									No skills in this pack.
								</div>
							{/if}
						</div>
					</details>
				{/each}
			</div>
		{/if}
		{/if}
	</div>
{:else}
	<div class="flex justify-center py-10"><Spinner className="size-5" /></div>
{/if}

<style>
	:global(.skill-pack > summary::-webkit-details-marker) {
		display: none;
	}
	:global(.skill-pack > summary) {
		list-style: none;
	}
	:global(.skill-pack[open] > summary .skill-pack-chevron) {
		transform: rotate(90deg);
	}
	:global(.skill-pack > summary .skill-pack-chevron) {
		display: inline-flex;
		transition: transform 0.15s ease;
	}
</style>
