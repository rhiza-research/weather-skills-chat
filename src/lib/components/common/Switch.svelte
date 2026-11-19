<script lang="ts">
	import { createEventDispatcher, onMount } from 'svelte';
	import { Switch } from 'bits-ui';
	export let state = true;
	export let disabled = false;

	const dispatch = createEventDispatcher();
	let el: HTMLButtonElement;

	$: if (!disabled) dispatch('change', state);

	// Name the switch from the label beside it when the caller gave none.
	onMount(() => {
		if (el?.hasAttribute('aria-label') || el?.hasAttribute('aria-labelledby')) return;
		for (let node: Element | null = el, i = 0; node && i < 3; node = node.parentElement, i++) {
			const text = node.previousElementSibling?.textContent?.trim();
			if (text && text.length < 120) return el.setAttribute('aria-label', text);
		}
	});
</script>

<Switch.Root
	bind:el
	bind:checked={state}
	{disabled}
	class="flex h-5 min-h-5 w-9 shrink-0 items-center rounded-full px-[3px] mx-[1px] transition outline outline-1 outline-gray-600 dark:outline-gray-500 {disabled
		? 'opacity-40 cursor-not-allowed'
		: 'cursor-pointer'} {state
		? ' bg-green-600'
		: 'bg-gray-200 dark:bg-transparent'}"
>
	<Switch.Thumb
		class="pointer-events-none block size-4 shrink-0 rounded-full bg-white transition-transform data-[state=checked]:translate-x-3.5 data-[state=unchecked]:translate-x-0 data-[state=unchecked]:shadow-mini "
	/>
</Switch.Root>
