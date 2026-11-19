<script lang="ts">
	import TagInput from './Tags/TagInput.svelte';
	import TagList from './Tags/TagList.svelte';
	import { getContext, createEventDispatcher } from 'svelte';
	const dispatch = createEventDispatcher();

	const i18n = getContext('i18n');

	export let tags = [];
	export let className = '';
</script>

{#if tags.length}
	<div class="flex flex-row flex-wrap items-center gap-1 {className}">
		<TagList {tags} on:delete={(e) => dispatch('delete', e.detail)} />
		<TagInput on:add={(e) => dispatch('add', e.detail)} />
	</div>
{:else}
	<TagInput label={$i18n.t('Add Tags')} on:add={(e) => dispatch('add', e.detail)} />
{/if}
