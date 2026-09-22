<script lang="ts">
	import { config } from '$lib/stores';
	import { helpEmailAddress } from '$lib/constants';

	/** Text shown before the address. */
	export let label = 'Need help?';
	export let className = 'text-xs text-gray-500 dark:text-gray-400';

	$: email = helpEmailAddress($config?.help_email);
</script>

<div class={className}>
	{label}
	<a class="underline" href={`mailto:${email}`}>{email}</a>
</div>
