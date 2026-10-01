<script lang="ts">
	import { settings, playingNotificationSound, isLastActiveTab } from '$lib/stores';

	import { createEventDispatcher, getContext, onMount } from 'svelte';
	import XMark from '$lib/components/icons/XMark.svelte';

	const dispatch = createEventDispatcher();
	const i18n = getContext('i18n');

	export let onClick: Function = () => {};
	export let title: string = 'HI';
	export let content: string;

	let html = '';

	onMount(async () => {
		const [{ default: DOMPurify }, { marked }] = await Promise.all([
			import('dompurify'),
			import('marked')
		]);
		html = DOMPurify.sanitize(marked(content) as string);
		if (!navigator.userActivation.hasBeenActive) {
			return;
		}

		if ($settings?.notificationSound ?? true) {
			if (!$playingNotificationSound && $isLastActiveTab) {
				playingNotificationSound.set(true);

				const audio = new Audio(`/audio/notification.mp3`);
				audio.play().finally(() => {
					// Ensure the global state is reset after the sound finishes
					playingNotificationSound.set(false);
				});
			}
		}
	});
</script>

<div
	class="relative flex min-w-[var(--width)] w-full dark:bg-gray-850 dark:text-white bg-white text-black border border-gray-100 dark:border-gray-850 rounded-xl"
>
	<button
		type="button"
		class="absolute top-1.5 right-1.5 z-10 rounded-md p-0.5 text-gray-400 hover:text-gray-700 dark:hover:text-gray-200"
		aria-label={$i18n.t('Close')}
		on:click|stopPropagation={() => dispatch('closeToast')}
	>
		<XMark className="size-3" strokeWidth="2.5" />
	</button>

	<button
		type="button"
		class="flex gap-2.5 text-left w-full px-3.5 py-3.5 pr-7"
		on:click={() => {
			onClick();
			dispatch('closeToast');
		}}
	>
		<div class="shrink-0 self-top -translate-y-0.5">
			<img src={'/static/favicon.png'} alt="favicon" class="size-7 rounded-full" />
		</div>

		<div>
			{#if title}
				<div class=" text-[13px] font-medium mb-0.5 line-clamp-1 capitalize">{title}</div>
			{/if}

			<div class=" line-clamp-2 text-xs self-center dark:text-gray-300 font-normal">
				{@html html}
			</div>
		</div>
	</button>
</div>
