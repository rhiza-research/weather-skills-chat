<script>
	// /s with no share id, or with extra path segments: not a share link.
	import { getContext, onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { toast } from 'svelte-sonner';

	const i18n = getContext('i18n');

	onMount(() => {
		toast.error($i18n.t('This share link does not exist or has expired.'));
		goto(localStorage.token ? '/' : '/auth');
	});
</script>
