<script lang="ts">
	import { createEventDispatcher, getContext } from 'svelte';
	import { tags } from '$lib/stores';
	import { toast } from 'svelte-sonner';
	import Check from '$lib/components/icons/Check.svelte';
	import Plus from '$lib/components/icons/Plus.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';
	const dispatch = createEventDispatcher();

	const i18n = getContext('i18n');

	export let label = '';
	let showTagInput = false;
	let tagName = '';

	const addTagHandler = async () => {
		tagName = tagName.trim();
		if (tagName !== '') {
			dispatch('add', tagName);
			tagName = '';
			showTagInput = false;
		} else {
			toast.error($i18n.t(`Invalid Tag`));
		}
	};
</script>

{#if showTagInput}
	<div class="flex items-center gap-1 {label ? 'px-3 py-1.5' : 'px-0.5'}">
		<input
			bind:value={tagName}
			class="field-bare text-sm w-[6.5rem]"
			placeholder={$i18n.t('Add a tag')}
			list="tagOptions"
			on:keydown={(event) => {
				if (event.key === 'Enter') addTagHandler();
				if (event.key === 'Escape') showTagInput = false;
			}}
		/>
		<datalist id="tagOptions">
			{#each $tags as tag}
				<option value={tag.name} />
			{/each}
		</datalist>

		<button
			class="btn-ghost btn-ghost-xs"
			type="button"
			aria-label={$i18n.t('Save Tag')}
			on:click={addTagHandler}
		>
			<Check className="size-4" />
		</button>
		<button
			class="btn-ghost btn-ghost-xs"
			type="button"
			aria-label={$i18n.t('Cancel')}
			on:click={() => (showTagInput = false)}
		>
			<XMark className="size-4" />
		</button>
	</div>
{:else if label}
	<button class="menu-item w-full" type="button" on:click={() => (showTagInput = true)}>
		<Plus className="size-4" strokeWidth="1.5" />
		{label}
	</button>
{:else}
	<button
		class="self-center p-0.5 flex rounded-full border border-dashed border-line-strong hover:bg-black/5 dark:hover:bg-white/5 transition"
		type="button"
		aria-label={$i18n.t('Add Tag')}
		on:click={() => (showTagInput = true)}
	>
		<Plus className="size-3" />
	</button>
{/if}
