<script lang="ts">
	import { onMount, getContext } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { goto } from '$app/navigation';
	import { tools as toolsStore, user } from '$lib/stores';
	import { getTools } from '$lib/apis/tools';
	import {
		deleteSkillPack,
		getSkillPacks,
		installSkillPack,
		updateSkillPack,
		updateSkillPackAccess,
		updateSkillEnabled
	} from '$lib/apis/skills';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import AccessControlModal from '$lib/components/workspace/common/AccessControlModal.svelte';
	import ChevronRight from '$lib/components/icons/ChevronRight.svelte';
	import Switch from '$lib/components/common/Switch.svelte';
	import { userCanSetSharingAccess } from '$lib/utils/accessControl';

	const i18n = getContext('i18n');

	let loaded = false;
	let busy = false;
	let packs = [];
	let gitUrl = '';
	let gitRef = 'main';
	let deletePackId = '';
	let showDeleteConfirm = false;
	let showAccessModal = false;
	let accessPack = null;
	let accessControl = {};
	let accessSaveTimeout = null;
	let lastSavedAccessKey = '';
	let accessSaveInFlight = false;
	let pendingAccessAcl = undefined;

	const shortSha = (sha: string) => (sha ? sha.slice(0, 7) : '');

	/** Canonicalize empty private ACL shapes so `{}` matches AccessControl's form. */
	const accessKey = (acl) => {
		if (acl === null || acl === undefined) {
			return 'null';
		}
		const read = acl.read || {};
		const write = acl.write || {};
		const empty =
			!(read.group_ids || []).length &&
			!(read.team_ids || []).length &&
			!(read.user_ids || []).length &&
			!(write.group_ids || []).length &&
			!(write.team_ids || []).length &&
			!(write.user_ids || []).length;
		if (empty) {
			return 'private';
		}
		return JSON.stringify(acl);
	};

	const accessLabel = (acl) => {
		if (acl === null) return 'Public';
		if (!acl || (Object.keys(acl).length === 0 && acl.constructor === Object)) return 'Private';
		const users = acl?.read?.user_ids?.length || 0;
		const groups = acl?.read?.group_ids?.length || 0;
		const teams = acl?.read?.team_ids?.length || 0;
		const bits = [];
		if (users) bits.push(`${users} user${users === 1 ? '' : 's'}`);
		if (groups) bits.push(`${groups} group${groups === 1 ? '' : 's'}`);
		if (teams) bits.push(`${teams} team${teams === 1 ? '' : 's'}`);
		return bits.length ? bits.join(', ') : 'Restricted';
	};

	const refresh = async () => {
		packs =
			(await getSkillPacks(localStorage.token).catch((error) => {
				toast.error(`${error}`);
				return [];
			})) || [];
	};

	/** Keep chat's shared tools list in sync after pack install/update/delete/toggle. */
	const refreshTools = async () => {
		try {
			await toolsStore.set(await getTools(localStorage.token));
		} catch (_) {}
	};

	const installHandler = async () => {
		if (!gitUrl.trim()) {
			toast.error('Git URL is required');
			return;
		}
		busy = true;
		const pack = await installSkillPack(
			localStorage.token,
			gitUrl.trim(),
			(gitRef || 'main').trim()
		).catch((error) => {
			toast.error(`${error}`);
			return null;
		});
		busy = false;
		if (pack) {
			toast.success(`Installed ${pack.skills?.length || 0} skill(s) from ${pack.git_ref}`);
			gitUrl = '';
			gitRef = 'main';
			await refresh();
			await refreshTools();
		}
	};

	const updateHandler = async (pack) => {
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

	const openAccess = (pack) => {
		if (accessSaveTimeout) {
			clearTimeout(accessSaveTimeout);
			accessSaveTimeout = null;
		}
		pendingAccessAcl = undefined;
		accessPack = pack;
		// Expand private `{}` before the modal mounts so AccessControl never
		// renders against a missing .read / .write shape.
		accessControl =
			pack.access_control === null
				? null
				: {
						read: {
							group_ids: pack.access_control?.read?.group_ids ?? [],
							team_ids: pack.access_control?.read?.team_ids ?? [],
							user_ids: pack.access_control?.read?.user_ids ?? []
						},
						write: {
							group_ids: pack.access_control?.write?.group_ids ?? [],
							team_ids: pack.access_control?.write?.team_ids ?? [],
							user_ids: pack.access_control?.write?.user_ids ?? []
						}
					};
		lastSavedAccessKey = accessKey(accessControl);
		showAccessModal = true;
	};

	const persistAccess = async (acl) => {
		if (!accessPack) return;

		if (accessSaveInFlight) {
			// Keep the latest user choice (e.g. Public) instead of dropping it
			// while a prior save is still propagating tool ACLs.
			pendingAccessAcl = acl;
			return;
		}

		const key = accessKey(acl);
		if (key === lastSavedAccessKey) return;

		accessSaveInFlight = true;
		const packId = accessPack.id;
		const updated = await updateSkillPackAccess(localStorage.token, packId, acl).catch(
			(error) => {
				toast.error(`${error}`);
				return null;
			}
		);
		accessSaveInFlight = false;

		if (updated) {
			lastSavedAccessKey = accessKey(updated.access_control);
			toast.success('Pack access updated for all skills');
			await refresh();
			await refreshTools();
			if (accessPack?.id === packId) {
				accessPack = { ...accessPack, access_control: updated.access_control };
			}
		}

		if (pendingAccessAcl !== undefined) {
			const next = pendingAccessAcl;
			pendingAccessAcl = undefined;
			await persistAccess(next);
		}
	};

	const saveAccess = (acl) => {
		if (!accessPack) return;
		// AccessControl fires onChange on every reactive tick; debounce and
		// skip no-ops so Public (null) does not re-enter save in a loop.
		if (accessSaveTimeout) {
			clearTimeout(accessSaveTimeout);
		}
		accessSaveTimeout = setTimeout(() => {
			accessSaveTimeout = null;
			persistAccess(acl);
		}, 400);
	};

	const deleteHandler = async () => {
		if (!deletePackId) return;
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

	const skillEnabled = (skill) => skill?.enabled !== false;

	const toggleSkillEnabled = async (pack, skill, enabled) => {
		if (!pack?.id || !skill?.tool_id) return;
		const previous = skillEnabled(skill);
		// Optimistic UI
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

		if (!updated) {
			skill.enabled = previous;
			packs = packs;
			return;
		}

		const idx = packs.findIndex((p) => p.id === pack.id);
		if (idx >= 0) {
			packs[idx] = updated;
			packs = packs;
		}
		await refreshTools();
	};

	onMount(async () => {
		if ($user?.role !== 'admin' && !$user?.permissions?.workspace?.skills) {
			goto('/');
			return;
		}
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

<AccessControlModal
	bind:show={showAccessModal}
	bind:accessControl
	allowPublic={userCanSetSharingAccess(
		$user,
		accessPack?.user_id,
		accessControl,
		'public_skills'
	)}
	onChange={saveAccess}
/>

{#if loaded}
	<div class="mb-3">
		<div class="text-lg font-medium mb-1">Skills</div>
		<div class="text-sm text-gray-500 dark:text-gray-400 mb-4">
			Install Agent Skills from a public git repo (include the branch/ref). Skills run like tools in
			chat but are managed here — expand a pack to enable/disable skills globally (new installs are
			all on). Disabled skills stay available in the chat tools menu. Set pack access to grant users
			the whole pack. To switch branches, remove the pack and install again at the new ref.
		</div>

		<div
			class="flex flex-col md:flex-row gap-2 mb-6 p-3 rounded-xl bg-gray-50 dark:bg-gray-850 border border-gray-100 dark:border-gray-800"
		>
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

		{#if busy}
			<div class="flex justify-center py-4"><Spinner /></div>
		{/if}

		{#if packs.length === 0}
			<div class="text-sm text-gray-500 dark:text-gray-400 py-6 text-center">
				No skill packs installed yet.
			</div>
		{:else}
			<div class="flex flex-col gap-3">
				{#each packs as pack (pack.id)}
					<details
						class="skill-pack rounded-xl border border-gray-100 dark:border-gray-800 bg-white dark:bg-gray-900"
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
										· access {accessLabel(pack.access_control)}
									</div>
								</div>
							</div>
							<!-- svelte-ignore a11y-click-events-have-key-events -->
							<!-- svelte-ignore a11y-no-static-element-interactions -->
							<div
								class="flex flex-wrap gap-1.5"
								on:click|stopPropagation
								on:mousedown|stopPropagation
							>
								<button
									type="button"
									class="text-xs px-2.5 py-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-850"
									disabled={busy}
									on:click|stopPropagation={() => openAccess(pack)}
								>
									Access
								</button>
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
													<span class="text-xs text-gray-400 ml-1">off by default</span>
												{/if}
												{#if skill.description}
													<div class="text-xs text-gray-500 dark:text-gray-400 line-clamp-2">
														{skill.description}
													</div>
												{/if}
											</div>
											{#if skill.tool_id}
												<!-- svelte-ignore a11y-click-events-have-key-events -->
												<!-- svelte-ignore a11y-no-static-element-interactions -->
												<div
													class="shrink-0 pt-0.5"
													on:click|stopPropagation
													on:mousedown|stopPropagation
												>
													<Switch
														state={skillEnabled(skill)}
														on:change={(e) => {
															const next = !!e.detail;
															if (next === skillEnabled(skill)) return;
															toggleSkillEnabled(pack, skill, next);
														}}
													/>
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
