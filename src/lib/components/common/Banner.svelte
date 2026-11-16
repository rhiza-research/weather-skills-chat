<script lang="ts" context="module">
	// `type` holds the label color; old type names still render in their old colors.
	export const BANNER_COLORS: Record<string, string> = {
		blue: 'bg-blue-500/20 text-blue-700 dark:text-blue-200',
		green: 'bg-green-500/20 text-green-700 dark:text-green-200',
		yellow: 'bg-yellow-500/20 text-yellow-700 dark:text-yellow-200',
		orange: 'bg-orange-500/20 text-orange-700 dark:text-orange-200',
		red: 'bg-red-500/20 text-red-700 dark:text-red-200',
		purple: 'bg-purple-500/20 text-purple-700 dark:text-purple-200',
		gray: 'bg-gray-500/20 text-gray-700 dark:text-gray-200'
	};
	export const LEGACY_BANNER_TYPES: Record<string, string> = {
		info: 'blue',
		success: 'green',
		warning: 'yellow',
		error: 'red'
	};
</script>

<script lang="ts">
	import type { Banner } from '$lib/types';
	import { onMount } from 'svelte';
	import { fade } from 'svelte/transition';
	let html = '';


	export let banner: Banner = {
		id: '',
		type: 'info',
		title: '',
		content: '',
		url: '',
		timestamp: Math.floor(Date.now() / 1000)
	};
	export let className = 'mx-4';

	$: if (banner?.content) {
		const content = banner.content;
		Promise.all([import('dompurify'), import('marked')]).then(([{ default: DOMPurify }, { marked }]) => {
			if (banner.content !== content) return;
			html = DOMPurify.sanitize(marked.parse(content) as string);
		});
	}


	let mounted = false;

	$: color =
		BANNER_COLORS[LEGACY_BANNER_TYPES[banner.type] ?? banner.type] ?? BANNER_COLORS.blue;
	// Banners saved before titles existed keep their old type name as the label.
	$: label = banner.title || (LEGACY_BANNER_TYPES[banner.type] ? banner.type : '');

	onMount(() => {
		mounted = true;
	});
</script>

{#if mounted}
	<div
		class="{className} top-0 left-0 right-0 p-2 px-3 flex justify-center items-center relative rounded-xl border border-gray-100 dark:border-gray-850 text-gray-800 dark:text-gary-100 bg-white dark:bg-gray-900 backdrop-blur-xl z-30"
		transition:fade={{ delay: 100, duration: 300 }}
	>
		<div class=" flex flex-col md:flex-row md:items-center flex-1 text-sm w-fit gap-1.5">
			<div class="flex justify-between self-start">
				<div
					class=" text-xs font-bold {color} w-fit {label
						? 'px-2'
						: 'p-1 self-center'} rounded-sm uppercase line-clamp-1 mr-0.5"
				>
					{#if label}
						{label}
					{:else}
						<div class="size-2 rounded-full bg-current"></div>
					{/if}
				</div>

				{#if banner.url}
					<div class="flex md:hidden group w-fit md:items-center">
						<a
							class="text-gray-700 dark:text-white text-xs font-semibold underline"
							href="/assets/files/whitepaper.pdf"
							target="_blank">Learn More</a
						>

						<div
							class=" ml-1 text-gray-400 group-hover:text-gray-600 dark:group-hover:text-white"
						>
							<!--  -->
							<svg
								xmlns="http://www.w3.org/2000/svg"
								viewBox="0 0 16 16"
								fill="currentColor"
								class="w-4 h-4"
							>
								<path
									fill-rule="evenodd"
									d="M4.22 11.78a.75.75 0 0 1 0-1.06L9.44 5.5H5.75a.75.75 0 0 1 0-1.5h5.5a.75.75 0 0 1 .75.75v5.5a.75.75 0 0 1-1.5 0V6.56l-5.22 5.22a.75.75 0 0 1-1.06 0Z"
									clip-rule="evenodd"
								/>
							</svg>
						</div>
					</div>
				{/if}
			</div>

			<div class="flex-1 text-xs text-gray-700 dark:text-white">
				{@html html}
			</div>
		</div>

		{#if banner.url}
			<div class="hidden md:flex group w-fit md:items-center">
				<a
					class="text-gray-700 dark:text-white text-xs font-semibold underline"
					href="/"
					target="_blank">Learn More</a
				>

				<div class=" ml-1 text-gray-400 group-hover:text-gray-600 dark:group-hover:text-white">
					<!--  -->
					<svg
						xmlns="http://www.w3.org/2000/svg"
						viewBox="0 0 16 16"
						fill="currentColor"
						class="size-4"
					>
						<path
							fill-rule="evenodd"
							d="M4.22 11.78a.75.75 0 0 1 0-1.06L9.44 5.5H5.75a.75.75 0 0 1 0-1.5h5.5a.75.75 0 0 1 .75.75v5.5a.75.75 0 0 1-1.5 0V6.56l-5.22 5.22a.75.75 0 0 1-1.06 0Z"
							clip-rule="evenodd"
						/>
					</svg>
				</div>
			</div>
		{/if}
	</div>
{/if}
