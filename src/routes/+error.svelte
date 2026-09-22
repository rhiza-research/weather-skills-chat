<script>
	import { page } from '$app/stores';
	import HelpContact from '$lib/components/common/HelpContact.svelte';
</script>

<div class=" bg-white dark:bg-gray-800 min-h-screen">
	<div class=" flex h-full">
		<div class="m-auto my-10 flex flex-col items-center gap-3 px-6 text-center">
			<div class="dark:text-gray-300 text-3xl font-semibold">
				{$page.status}: {$page.error?.message ?? 'Sorry, something went wrong'}
			</div>

			<a class="text-sm underline text-gray-500 dark:text-gray-400" href="/">Back to chat</a>

			<HelpContact
				className="text-xs text-gray-500 dark:text-gray-400"
				label="Need help? Contact"
			/>
		</div>
	</div>
</div>
