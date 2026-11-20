<script lang="ts">
	import { onMount, getContext } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { organizations, activeOrganizationId, textSkills, user } from '$lib/stores';
	import {
		createTextSkill,
		deleteTextSkillById,
		getTextSkills,
		updateTextSkillById,
		type TextSkill
	} from '$lib/apis/textSkills';

	import Badge from '$lib/components/common/Badge.svelte';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import Plus from '$lib/components/icons/Plus.svelte';
	import Switch from '$lib/components/common/Switch.svelte';

	const i18n = getContext('i18n');

	let skills: TextSkill[] = [];
	let showAdd = false;
	let title = '';
	let content = '';
	let visibility: TextSkill['visibility'] = 'private';
	let editing: string | null = null;
	let editTitle = '';
	let editContent = '';
	let selected: TextSkill | null = null;
	let showDeleteConfirm = false;

	$: currentOrg = ($organizations ?? []).find((org) => org.id === $activeOrganizationId);
	$: isPersonal =
		!currentOrg || currentOrg.kind === 'personal' || $activeOrganizationId === $user?.id;
	$: isOrgAdmin = currentOrg?.role === 'owner' || currentOrg?.role === 'admin';

	const refresh = async () => {
		skills = await getTextSkills(localStorage.token).catch((error) => {
			toast.error(`${error}`);
			return [];
		});
		// The chat picker reads the same list.
		textSkills.set(skills);
	};

	const run = async (action: () => Promise<unknown>) => {
		try {
			await action();
			await refresh();
			return true;
		} catch (error) {
			toast.error(`${error}`);
			return false;
		}
	};

	const upload = async (event: Event) => {
		const input = event.target as HTMLInputElement;
		const file = input.files?.[0];
		input.value = '';
		if (!file) return;
		content = await file.text();
		if (!title.trim()) {
			const name = content.match(/^---\s*\n[\s\S]*?^name:\s*["']?(.+?)["']?\s*$/m)?.[1];
			title = name ?? file.name.replace(/\.(md|markdown)$/i, '');
		}
	};

	const submit = async () => {
		const ok = await run(() =>
			createTextSkill(localStorage.token, {
				title: title.trim(),
				content,
				visibility: isPersonal ? 'private' : visibility
			})
		);
		if (ok) {
			title = '';
			content = '';
			visibility = 'private';
			showAdd = false;
		}
	};

	const saveEdit = async (skill: TextSkill) => {
		const ok = await run(() =>
			updateTextSkillById(localStorage.token, skill.id, {
				title: editTitle.trim(),
				content: editContent
			})
		);
		if (ok) editing = null;
	};

	// Switch dispatches its state on mount too, so only write when it changes.
	const setFlag = (skill: TextSkill, key: 'enabled' | 'enabled_by_default', value: boolean) => {
		if (!skill.can_manage || skill[key] === value) return;
		run(() => updateTextSkillById(localStorage.token, skill.id, { [key]: value }));
	};

	onMount(refresh);
</script>

<ConfirmDialog
	bind:show={showDeleteConfirm}
	title={$i18n.t('Delete')}
	message={$i18n.t('Delete this skill?')}
	onConfirm={() => {
		const id = selected?.id;
		if (id) run(() => deleteTextSkillById(localStorage.token, id));
	}}
/>

<div class="mb-8">
	<div class="flex justify-between items-center mb-1">
		<div class="text-lg font-medium">{$i18n.t('Skills')}</div>
		<button
			class="px-2 py-2 rounded-xl hover:bg-gray-700/10 dark:hover:bg-gray-100/10 dark:text-gray-300 dark:hover:text-white transition"
			aria-label={$i18n.t('Add a skill')}
			on:click={() => (showAdd = !showAdd)}
		>
			<Plus className="size-3.5" />
		</button>
	</div>
	<div class="text-sm text-gray-500 dark:text-gray-400 mb-3">
		{$i18n.t(
			'Skills are written instructions, such as how to write a report. Turn them on for a chat in the chat bar. Organization skills are shared with every member.'
		)}
	</div>

	{#if showAdd}
		<form
			class="flex flex-col gap-2 mb-4 p-3 rounded-xl bg-gray-50 dark:bg-gray-850 border border-gray-100 dark:border-gray-800"
			on:submit|preventDefault={submit}
		>
			<input
				class="w-full text-sm rounded-lg py-2 px-3 bg-transparent outline-hidden"
				placeholder={$i18n.t('Title')}
				aria-label={$i18n.t('Title')}
				bind:value={title}
				required
			/>
			<textarea
				class="w-full min-h-40 text-sm font-mono rounded-lg py-2 px-3 bg-transparent outline-hidden border border-gray-200 dark:border-gray-700"
				placeholder={$i18n.t('Skill instructions in markdown')}
				aria-label={$i18n.t('Skill instructions')}
				bind:value={content}
				required
			></textarea>
			<div class="flex flex-col md:flex-row gap-2 md:items-center md:justify-between">
				<div class="flex flex-col md:flex-row gap-2 md:items-center">
					<label
						class="text-sm px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 cursor-pointer text-center hover:bg-gray-100 dark:hover:bg-gray-800"
					>
						{$i18n.t('Upload .md file')}
						<input type="file" accept=".md,.markdown,text/markdown" class="hidden" on:change={upload} />
					</label>
					{#if !isPersonal && isOrgAdmin}
						<select
							class="md:w-40 w-full text-sm rounded-lg py-2 px-3 bg-transparent outline-hidden border border-gray-200 dark:border-gray-700"
							aria-label={$i18n.t('Visibility')}
							bind:value={visibility}
						>
							<option value="private">{$i18n.t('Private')}</option>
							<option value="organization">{$i18n.t('Organization')}</option>
						</select>
					{/if}
				</div>
				<button
					class="px-3.5 py-2 text-sm rounded-lg bg-gray-900 text-white dark:bg-white dark:text-gray-900"
					type="submit"
				>
					{$i18n.t('Save')}
				</button>
			</div>
		</form>
	{/if}

	<div class="flex flex-col gap-2">
		{#each skills as skill (skill.id)}
			<div
				class="px-3 py-3 rounded-xl border border-gray-100 dark:border-gray-800 bg-white dark:bg-gray-900 {skill.enabled
					? ''
					: 'opacity-60'}"
			>
				<div class="flex flex-col md:flex-row md:items-center justify-between gap-2">
					<div class="flex items-center gap-2 min-w-0">
						{#if skill.visibility === 'organization'}
							<Badge type="success" content={$i18n.t('Organization')} />
						{:else}
							<Badge type="muted" content={$i18n.t('Private')} />
						{/if}
						<div class="font-semibold truncate">{skill.title}</div>
					</div>
					{#if skill.can_manage}
						<div class="flex items-center gap-4 shrink-0 text-xs text-gray-500">
							<label class="flex items-center gap-2">
								<Switch
									state={skill.enabled}
									on:change={(e) => setFlag(skill, 'enabled', !!e.detail)}
								/>
								{$i18n.t('Enabled')}
							</label>
							<label class="flex items-center gap-2">
								<Switch
									state={skill.enabled_by_default}
									on:change={(e) => setFlag(skill, 'enabled_by_default', !!e.detail)}
								/>
								{$i18n.t('On by default')}
							</label>
						</div>
					{:else}
						<span class="text-xs text-gray-500">
							{skill.enabled
								? skill.enabled_by_default
									? $i18n.t('On by default')
									: $i18n.t('Off by default')
								: $i18n.t('Disabled')}
						</span>
					{/if}
				</div>

				{#if editing === skill.id}
					<div class="mt-3 flex flex-col gap-2">
						<input
							class="w-full text-sm rounded-lg py-2 px-3 bg-transparent outline-hidden border border-gray-200 dark:border-gray-700"
							aria-label={$i18n.t('Title')}
							bind:value={editTitle}
						/>
						<textarea
							class="w-full min-h-40 text-sm font-mono rounded-lg py-2 px-3 bg-transparent outline-hidden border border-gray-200 dark:border-gray-700"
							aria-label={$i18n.t('Skill instructions')}
							bind:value={editContent}
						></textarea>
						<div class="flex gap-2">
							<button
								class="text-xs px-2 py-1.5 rounded-lg bg-gray-900 text-white dark:bg-white dark:text-gray-900"
								on:click={() => saveEdit(skill)}
							>
								{$i18n.t('Save')}
							</button>
							<button
								class="text-xs px-2 py-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800"
								on:click={() => (editing = null)}
							>
								{$i18n.t('Cancel')}
							</button>
						</div>
					</div>
				{:else}
					<details class="mt-2">
						<summary class="text-xs text-gray-500 cursor-pointer select-none">
							{$i18n.t('Show instructions')}
						</summary>
						<div
							class="mt-2 text-sm font-mono text-gray-600 dark:text-gray-300 whitespace-pre-wrap max-h-80 overflow-y-auto"
						>
							{skill.content}
						</div>
					</details>
					{#if skill.can_manage}
						<div class="mt-2 flex gap-1">
							<button
								class="text-xs px-2 py-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800"
								on:click={() => {
									editing = skill.id;
									editTitle = skill.title;
									editContent = skill.content;
								}}
							>
								{$i18n.t('Edit')}
							</button>
							<button
								class="text-xs px-2 py-1.5 rounded-lg text-red-600 hover:bg-red-50 dark:hover:bg-red-950"
								on:click={() => {
									selected = skill;
									showDeleteConfirm = true;
								}}
							>
								{$i18n.t('Delete')}
							</button>
						</div>
					{/if}
				{/if}
			</div>
		{:else}
			<div class="text-sm text-gray-500 dark:text-gray-400 py-4">
				{$i18n.t('No skills yet.')}
			</div>
		{/each}
	</div>
</div>
