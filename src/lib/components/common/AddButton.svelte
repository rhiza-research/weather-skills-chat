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
	class="shrink-0 whitespace-nowrap px-3 py-1.5 rounded-full border border-gray-300 dark:border-gray-600 text-gray-800 dark:text-gray-100 hover:bg-gray-100 dark:hover:bg-gray-800 transition font-medium text-sm flex items-center gap-1.5"
	on:click
>
	<Plus className="size-3.5" strokeWidth="2.5" />
	{label}
</svelte:element>
