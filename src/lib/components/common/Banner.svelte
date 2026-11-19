<script lang="ts" context="module">
	// `type` holds the label color; old type names still render in their old colors.
	export const BANNER_COLORS: Record<string, string> = {
		blue: 'bg-blue-500/20 text-blue-700 dark:text-blue-200',
		green: 'bg-green-500/20 text-green-700 dark:text-green-200',
		yellow: 'bg-yellow-500/20 text-yellow-700 dark:text-yellow-200',
		orange: 'bg-orange-500/20 text-orange-700 dark:text-orange-200',
		red: 'bg-red-500/20 text-red-700 dark:text-red-200',
		purple: 'bg-blue-500/20 text-blue-700 dark:text-blue-200',
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
	import ArrowUpRightSolid from '$lib/components/icons/ArrowUpRightSolid.svelte';
	import type { Banner } from '$lib/types';
	import { onMount, createEventDispatcher, getContext } from 'svelte';
	import { fade } from 'svelte/transition';

	const i18n = getContext('i18n');
	let html = '';

	const dispatch = createEventDispatcher();

	export let banner: Banner = {
		id: '',
		type: 'info',
		title: '',
		content: '',
		url: '',
		dismissable: true,
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

	export let dismissed = false;

	let mounted = false;

	$: color =
		BANNER_COLORS[LEGACY_BANNER_TYPES[banner.type] ?? banner.type] ?? BANNER_COLORS.blue;
	// Banners saved before titles existed keep their old type name as the label.
	$: label = banner.title || (LEGACY_BANNER_TYPES[banner.type] ? banner.type : '');

	const dismiss = (id) => {
		dismissed = true;
		dispatch('dismiss', id);
	};

	onMount(() => {
		mounted = true;
	});
</script>

{#if !dismissed}
	{#if mounted}
		<div
			class="{className} top-0 left-0 right-0 p-2 px-3 flex justify-center items-center relative rounded-xl border border-line text-gray-800 dark:text-gary-100 bg-white dark:bg-gray-900 backdrop-blur-xl z-30"
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
								target="_blank">{$i18n.t('Learn More')}</a
							>

							<div
								class="ml-1 text-muted group-hover:text-gray-600 dark:group-hover:text-white"
							>
								<!--  -->
								<ArrowUpRightSolid className="size-4" />
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
						target="_blank">{$i18n.t('Learn More')}</a
					>

					<div class="ml-1 text-muted group-hover:text-gray-600 dark:group-hover:text-white">
						<!--  -->
						<ArrowUpRightSolid className="size-4" />
					</div>
				</div>
			{/if}
			<div class="flex self-start">
				{#if banner.dismissible}
					<button
						on:click={() => {
							dismiss(banner.id);
						}}
						class="-mt-1 -mb-2 -translate-y-[1px] ml-1.5 mr-1 text-muted dark:hover:text-white"
						>&times;</button
					>
				{/if}
			</div>
		</div>
	{/if}
{/if}
