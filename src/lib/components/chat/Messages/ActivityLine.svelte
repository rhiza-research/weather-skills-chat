<script lang="ts">
	import { getContext, onDestroy } from 'svelte';
	import { slide } from 'svelte/transition';
	import { quintOut } from 'svelte/easing';
	import dayjs from 'dayjs';
	import duration from 'dayjs/plugin/duration';
	import { decodeEntities } from '$lib/utils/entities';
	import ChevronUp from '$lib/components/icons/ChevronUp.svelte';
	import ChevronDown from '$lib/components/icons/ChevronDown.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';

	dayjs.extend(duration);

	const i18n = getContext('i18n');

	export let items: any[] = [];
	export let status: {
		done?: boolean;
		hidden?: boolean;
		action?: string;
		description?: string;
	} | null = null;

	let localOpen = false;
	let nowMs = Date.now();
	let timer: ReturnType<typeof setInterval> | null = null;

	const toggleOpen = () => {
		localOpen = !localOpen;
	};

	const unwrapJSON = (value: any): any => {
		if (typeof value !== 'string') return value;
		const trimmed = value.trim();
		if (!trimmed) return value;
		try {
			return unwrapJSON(JSON.parse(trimmed));
		} catch {
			return value;
		}
	};

	const toolArgs = (item: any) => unwrapJSON(decodeEntities(item?.attributes?.arguments ?? ''));

	const formatElapsed = (seconds: number) => {
		if (!Number.isFinite(seconds) || seconds < 0) return '';
		const whole = Math.floor(seconds);
		if (whole < 60) return `${whole}s`;
		const minutes = Math.floor(whole / 60);
		const rem = whole % 60;
		return rem ? `${minutes}m ${rem}s` : `${minutes}m`;
	};

	$: incomplete = items.filter((item) => item?.attributes?.done !== 'true');
	$: waiting =
		Boolean(status) && status?.hidden !== true && status?.done === false && Boolean(status?.description);
	$: live = incomplete.length > 0 || waiting;
	$: runningTools = incomplete.filter((item) => item?.attributes?.type === 'tool_calls');
	$: thinking = incomplete.some((item) => item?.attributes?.type === 'reasoning');
	$: analyzing = incomplete.some((item) => item?.attributes?.type === 'code_interpreter');

	$: earliestStart = (() => {
		let min: number | null = null;
		for (const item of runningTools) {
			const started = Number(item?.attributes?.started_at);
			if (Number.isFinite(started) && (min === null || started < min)) min = started;
		}
		return min;
	})();

	$: {
		if (live && earliestStart !== null) {
			if (!timer) {
				nowMs = Date.now();
				timer = setInterval(() => {
					nowMs = Date.now();
				}, 1000);
			}
		} else if (timer) {
			clearInterval(timer);
			timer = null;
		}
	}

	$: elapsedLabel =
		earliestStart !== null
			? formatElapsed(Math.max(0, Math.floor(nowMs / 1000 - earliestStart)))
			: '';

	$: liveHeadline = (() => {
		if (runningTools.length > 1) {
			let activity = '';
			for (const item of runningTools) {
				const args = toolArgs(item);
				const phrase = typeof args?.activity === 'string' ? args.activity.trim() : '';
				if (phrase) {
					activity = phrase;
					break;
				}
			}
			const label =
				activity ||
				$i18n.t('Running {{COUNT}} skills', { COUNT: runningTools.length });
			return elapsedLabel ? `${label} (${elapsedLabel})…` : `${label}…`;
		}
		if (runningTools.length === 1) {
			const item = runningTools[0];
			const args = toolArgs(item);
			const display = typeof args?.display === 'string' ? args.display.trim() : '';
			const name = item?.attributes?.name || 'tool';
			const label = display || `${$i18n.t('Running')} ${name}`;
			return elapsedLabel ? `${label} (${elapsedLabel})…` : `${label}…`;
		}
		if (analyzing) return $i18n.t('Analyzing...');
		if (thinking) return $i18n.t('Thinking...');
		if (waiting) return status?.description ?? '';
		return '';
	})();

	$: summaryHeadline = (() => {
		const seconds = items.reduce((total, item) => {
			if (item?.attributes?.type !== 'reasoning') return total;
			const durationSeconds = Number(item.attributes?.duration);
			return Number.isFinite(durationSeconds) && durationSeconds > 0
				? total + durationSeconds
				: total;
		}, 0);
		const skills = items.filter((item) => item?.attributes?.type === 'tool_calls').length;
		const parts = [];
		if (Number.isFinite(seconds) && seconds > 0) {
			parts.push(
				seconds < 60
					? $i18n.t('Thought for {{DURATION}} seconds', { DURATION: seconds })
					: $i18n.t('Thought for {{DURATION}}', {
							DURATION: dayjs.duration(seconds, 'seconds').humanize()
						})
			);
		}
		if (skills === 1) parts.push($i18n.t('Called {{COUNT}} skill', { COUNT: 1 }));
		else if (skills > 1) parts.push($i18n.t('Called {{COUNT}} skills', { COUNT: skills }));
		if (!parts.length && items.some((item) => item?.attributes?.type === 'code_interpreter')) {
			parts.push($i18n.t('Analyzed'));
		}
		if (parts.length === 2 && parts[1].startsWith('Called')) {
			return `${parts[0]}, ${parts[1].charAt(0).toLowerCase()}${parts[1].slice(1)}`;
		}
		return parts.join(', ');
	})();

	$: headline = live ? liveHeadline : summaryHeadline;

	onDestroy(() => {
		if (timer) clearInterval(timer);
	});
</script>

{#if headline}
	<div class="w-full space-y-1">
		<!-- svelte-ignore a11y-no-static-element-interactions -->
		<!-- svelte-ignore a11y-click-events-have-key-events -->
		<div
			class="w-fit text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 transition cursor-pointer"
			on:pointerup={toggleOpen}
		>
			<div class="w-full font-medium flex items-center gap-2 {live ? 'shimmer' : ''}">
				{#if live}
					<Spinner className="size-4" />
				{/if}
				<div class="text-gray-500 dark:text-gray-500 text-base line-clamp-1 text-wrap">
					{headline}
				</div>
				<div class="flex self-center translate-y-[1px]">
					{#if localOpen}
						<ChevronUp strokeWidth="3.5" className="size-3.5" />
					{:else}
						<ChevronDown strokeWidth="3.5" className="size-3.5" />
					{/if}
				</div>
			</div>
		</div>

		{#if localOpen}
			<!-- svelte-ignore a11y-no-static-element-interactions -->
			<div
				class="mt-1.5 ml-1 border-l border-gray-200 pl-3 dark:border-gray-700 space-y-1"
				transition:slide={{ duration: 300, easing: quintOut, axis: 'y' }}
				on:pointerup={(e) => e.stopPropagation()}
			>
				<slot />
			</div>
		{/if}
	</div>
{/if}
