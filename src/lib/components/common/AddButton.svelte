<script lang="ts">
	import Plus from '$lib/components/icons/Plus.svelte';

	export let label: string;
	// A link when set; otherwise a button that forwards on:click.
	export let href: string | null = null;
</script>

<svelte:element
	this={href ? 'a' : 'button'}
	{href}
	type={href ? undefined : 'button'}
	class="shrink-0 whitespace-nowrap px-3 py-1.5 rounded-lg bg-gray-900 text-white dark:bg-white dark:text-gray-900 transition font-medium text-sm flex items-center gap-1.5"
	on:click
>
	<Plus className="size-3.5" strokeWidth="2.5" />
	{label}
</svelte:element>
