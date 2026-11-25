<script lang="ts">
	import { onDestroy, onMount, tick } from 'svelte';
	import { fade } from 'svelte/transition';

	import { flyAndScale } from '$lib/utils/transitions';

	export let show = true;
	export let size = 'md';
	export let containerClassName = 'p-3';
	export let className = 'bg-white dark:bg-gray-900 rounded-2xl';

	let modalElement = null;
	let panel: HTMLElement;
	let mounted = false;
	let opener: HTMLElement | null = null;
	let opened = false;

	const FOCUSABLE =
		'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"]), [contenteditable="true"]';
	const focusables = () =>
		[...panel.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((e) => e.offsetParent !== null);

	// Remember what opened the modal; a dropdown item is gone by close time, so use its menu's trigger.
	const rememberOpener = () => {
		const active = document.activeElement as HTMLElement | null;
		const menu = active?.closest('[role="menu"]');
		opener = (menu?.id && document.querySelector<HTMLElement>(`[aria-controls="${menu.id}"]`)) || active;
	};

	// Keep focus in the top modal, e.g. when a closing menu hands focus back to its trigger.
	// Menus and listboxes the dialog itself opens live outside it and are allowed.
	const keepFocus = (event: FocusEvent) => {
		const target = event.target as HTMLElement;
		if (!isTopModal() || panel?.contains(target)) return;
		if (target.closest('[role="tooltip"], [data-tippy-root], .modal')) return;
		const popup = target.closest('[role="menu"], [role="listbox"]');
		if (popup?.id && panel?.querySelector(`[aria-controls="${popup.id}"]`)) return;
		requestAnimationFrame(() => (focusables()[0] ?? panel)?.focus());
	};

	const open = async () => {
		await tick();
		const title = panel?.querySelector('h1, h2, h3');
		if (title) {
			title.id ||= `modal-title-${Math.random().toString(36).slice(2, 8)}`;
			panel.setAttribute('aria-labelledby', title.id);
		}
		if (panel && !panel.contains(document.activeElement)) (focusables()[0] ?? panel).focus();
	};

	const sizeToWidth = (size) => {
		if (size === 'full') {
			return 'w-full';
		}
		if (size === 'xs') {
			return 'w-[16rem]';
		} else if (size === 'sm') {
			return 'w-[30rem]';
		} else if (size === 'md') {
			return 'w-[42rem]';
		} else {
			return 'w-[56rem]';
		}
	};

	const handleKeyDown = (event: KeyboardEvent) => {
		if (!isTopModal()) return;
		if (event.key === 'Escape') {
			show = false;
		} else if (event.key === 'Tab') {
			const items = focusables();
			if (!items.length) return event.preventDefault();
			const [first, last] = [items[0], items[items.length - 1]];
			if (event.shiftKey && document.activeElement === first) {
				event.preventDefault();
				last.focus();
			} else if (!event.shiftKey && (document.activeElement === last || !panel.contains(document.activeElement))) {
				event.preventDefault();
				first.focus();
			}
		}
	};

	const isTopModal = () => {
		const modals = document.getElementsByClassName('modal');
		return modals.length && modals[modals.length - 1] === modalElement;
	};

	onMount(() => {
		mounted = true;
	});

	$: if (show && modalElement) {
		if (!opened) {
			opened = true;
			rememberOpener();
			open();
		}
		document.body.appendChild(modalElement);
		window.addEventListener('keydown', handleKeyDown);
		document.addEventListener('focusin', keepFocus, true);
		document.body.style.overflow = 'hidden';
	} else if (modalElement) {
		window.removeEventListener('keydown', handleKeyDown);
		document.removeEventListener('focusin', keepFocus, true);
		document.body.removeChild(modalElement);
		document.body.style.overflow = 'unset';
		if (opener?.isConnected) opener.focus();
		opener = null;
		opened = false;
	}

	onDestroy(() => {
		show = false;
		document.removeEventListener('focusin', keepFocus, true);
		if (modalElement) {
			document.body.removeChild(modalElement);
		}
	});
</script>

{#if show}
	<!-- svelte-ignore a11y-click-events-have-key-events -->
	<!-- svelte-ignore a11y-no-static-element-interactions -->
	<div
		bind:this={modalElement}
		class="modal fixed top-0 right-0 left-0 bottom-0 bg-black/60 w-full h-screen max-h-[100dvh] {containerClassName} flex justify-center z-9999 overflow-y-auto overscroll-contain"
		in:fade={{ duration: 10 }}
		on:mousedown={() => {
			show = false;
		}}
	>
		<div
			bind:this={panel}
			role="dialog"
			aria-modal="true"
			tabindex="-1"
			class="m-auto max-w-full text-strong outline-none {sizeToWidth(size)} {size !== 'full'
				? 'mx-2'
				: ''} shadow-3xl min-h-fit scrollbar-hidden {className}"
			in:flyAndScale
			on:mousedown={(e) => {
				e.stopPropagation();
			}}
		>
			<slot />
		</div>
	</div>
{/if}

