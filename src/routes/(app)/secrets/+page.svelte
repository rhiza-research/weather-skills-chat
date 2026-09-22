<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';

	onMount(() => {
		const search = window.location.search || '';
		goto(`/workspace/secrets${search}`);
	});
</script>
