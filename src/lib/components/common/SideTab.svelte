<script lang="ts">
	export let id: string;
	export let label: string;
	export let selected: string;
</script>

<button
	class="px-2 py-1.5 min-w-fit rounded-lg flex-1 md:flex-none flex text-left transition {selected ===
	id
		? 'bg-tint'
		: 'text-muted hover:text-strong hover:bg-tint'}"
	on:click={() => (selected = id)}
>
	<div class="self-center mr-2"><slot /></div>
	<div class="self-center">{label}</div>
</button>
