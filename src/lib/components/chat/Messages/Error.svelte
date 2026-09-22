<script lang="ts">
	import Info from '$lib/components/icons/Info.svelte';
	import { config } from '$lib/stores';
	import { helpEmailAddress } from '$lib/constants';

	export let content = '';

	$: email = helpEmailAddress($config?.help_email);
</script>

<div class="flex my-2 gap-2.5 border px-4 py-3 border-red-600/10 bg-red-600/10 rounded-lg">
	<div class=" self-start mt-0.5">
		<Info className="size-5 text-red-700 dark:text-red-400" />
	</div>

	<div class="flex flex-col gap-1">
		<div class=" self-start text-sm">
			{typeof content === 'string' ? content : JSON.stringify(content)}
		</div>

		<div class="text-xs text-gray-600 dark:text-gray-400">
			If this keeps happening, contact
			<a class="underline" href={`mailto:${email}`}>{email}</a>
		</div>
	</div>
</div>
