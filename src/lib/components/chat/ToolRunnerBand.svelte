<script lang="ts">
	import { getContext } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { chatId, chatRunner, config, temporaryChatEnabled } from '$lib/stores';
	import { getToolRunner, getToolRunnerSizes, setToolRunnerSize } from '$lib/apis/chats';
	import { fmtCpu, fmtMemGib, runnerResourcesLine } from '$lib/chat/runnerResources';

	const i18n = getContext('i18n');

	// Linux keeps a little swap after pressure passes (swap-cache slots and idle
	// pages of the runtime), so only flag swap well above that leftover.
	const SWAP_FLAG_BYTES = 500 * 1024 ** 2;

	type Sample = { t: number; cpu: number; memory: number; swap: boolean };
	type Size = {
		type: string;
		display_name: string;
		description?: string;
		warm?: boolean;
		requires_approval?: boolean;
		cpus?: number | null;
		memory_gib?: number | null;
		default?: boolean;
	};
	type BandState = 'hidden' | 'paused' | 'starting' | 'ready' | 'degraded';

	let state: BandState = 'hidden';
	let open = false;
	let samples: Sample[] = [];
	let lastCpuUsage: number | null = null;
	let lastCpuTime: number | null = null;
	// Unknown until the runner's metrics report them; no limits are shown until then.
	let cpuLimit: number | null = null;
	let memLimitBytes: number | null = null;
	let startedFor = '';
	let ensuring = false;
	// The chat's runner size, and the sizes it can switch to (read when the menu opens).
	let size: Size | null = null;
	let sizes: Size[] = [];
	let switching = '';

	$: enabled = Boolean($config?.features?.enable_tool_runner);
	$: visible = enabled && !$temporaryChatEnabled && $chatId && $chatId !== 'local';

	$: if (visible && $chatId && $chatId !== startedFor) {
		startedFor = $chatId;
		resetBand();
		state = 'paused';
		readStatus($chatId);
	} else if (!visible) {
		startedFor = '';
		state = 'hidden';
		open = false;
		samples = [];
	}

	$: if (visible && $chatRunner?.id === $chatId) {
		applyLive($chatRunner);
	}

	const resetBand = () => {
		open = false;
		samples = [];
		lastCpuUsage = null;
		lastCpuTime = null;
		cpuLimit = null;
		memLimitBytes = null;
		size = null;
		sizes = [];
		switching = '';
	};

	const readStatus = async (id: string) => {
		if (ensuring) return;
		ensuring = true;
		try {
			const res = await getToolRunner(localStorage.token, id);
			if (id !== $chatId) return;
			if (res?.enabled === false) {
				state = 'hidden';
				return;
			}
			if (
				(state === 'starting' || state === 'ready') &&
				(res?.state === 'paused' || res?.state === 'absent')
			) {
				return;
			}
			applyLive(res);
		} catch {
			if (id === $chatId && state === 'hidden') state = 'paused';
		} finally {
			ensuring = false;
		}
	};

	const cpuCores = (metrics: any): number => {
		const usage = metrics?.cpu?.usage_usec;
		const now = metrics?.timestamp ?? Date.now() / 1000;
		if (typeof usage !== 'number' || lastCpuUsage == null || lastCpuTime == null) {
			lastCpuUsage = typeof usage === 'number' ? usage : null;
			lastCpuTime = now;
			return 0;
		}
		const dt = now - lastCpuTime;
		const du = usage - lastCpuUsage;
		lastCpuUsage = usage;
		lastCpuTime = now;
		if (dt <= 0) return 0;
		const cores = Math.max(0, du / 1_000_000 / dt);
		return cpuLimit ? Math.min(cpuLimit, cores) : cores;
	};

	const applyMetrics = (metrics: Record<string, any>) => {
		if (typeof metrics.cpu_limit === 'number' && metrics.cpu_limit > 0) {
			cpuLimit = metrics.cpu_limit;
		}
		if (typeof metrics.memory_limit_bytes === 'number' && metrics.memory_limit_bytes > 0) {
			memLimitBytes = metrics.memory_limit_bytes;
		}
		const next: Sample = {
			t: Date.now(),
			cpu: cpuCores(metrics),
			memory: Number(metrics.memory_bytes || 0),
			swap: Number(metrics.memory_swap_current || 0) > SWAP_FLAG_BYTES
		};
		samples = [...samples.filter((s) => Date.now() - s.t < 60_000), next];
	};

	const applyLive = (row: {
		state?: string;
		metrics?: Record<string, any> | null;
		size?: Size | null;
	}) => {
		if (row.size) {
			if (size && row.size.type !== size.type) {
				// Another size: its limits come with its first metrics.
				cpuLimit = null;
				memLimitBytes = null;
				samples = [];
				lastCpuUsage = null;
			}
			size = row.size;
		}
		if (row.state === 'ready') state = 'ready';
		else if (row.state === 'degraded') {
			// The runner reports itself unhealthy, or its pod is not ready, or it
			// has not answered for a while. It is replaced only when its claim goes.
			open = false;
			state = 'degraded';
		} else if (row.state === 'starting') {
			if (state === 'ready') open = false;
			state = 'starting';
		} else if (row.state === 'paused' || row.state === 'absent') {
			if (state === 'ready') open = false;
			state = 'paused';
		} else if (row.state === 'off') {
			state = 'hidden';
		}
		if (row.metrics) applyMetrics(row.metrics);
	};

	const loadSizes = async (id: string) => {
		const res = await getToolRunnerSizes(localStorage.token, id).catch(() => null);
		if (id !== $chatId || !res) return;
		sizes = res.sizes ?? [];
	};

	const toggle = () => {
		if (state === 'hidden') return;
		open = !open;
		if (open && $chatId) loadSizes($chatId);
	};

	const pickSize = async (next: Size) => {
		if (!$chatId || next.type === size?.type || switching) return;
		switching = next.type;
		const id = $chatId;
		try {
			const res = await setToolRunnerSize(localStorage.token, id, next.type);
			if (id !== $chatId) return;
			open = false;
			applyLive({ ...res, size: res?.size ?? next });
		} catch (error) {
			toast.error(`${error}`);
		} finally {
			switching = '';
		}
	};

	const sizeLimits = (s: Size) =>
		[s.cpus ? `${fmtCpu(s.cpus)} CPU` : '', s.memory_gib ? `${Math.round(s.memory_gib)} GB` : '']
			.filter(Boolean)
			.join(' · ');

	$: latest = samples[samples.length - 1];
	$: resources = runnerResourcesLine(latest, cpuLimit, memLimitBytes);
	$: statusLabel =
		state === 'ready'
			? $i18n.t('Weather skills runner ready')
			: state === 'paused'
				? $i18n.t('Weather skills runner paused')
				: state === 'degraded'
					? $i18n.t('Weather skills runner degraded')
					: $i18n.t('Weather skills runner starting');
	$: cpuPct = latest && cpuLimit ? Math.min(100, (latest.cpu / cpuLimit) * 100) : 0;
	$: memPct = latest && memLimitBytes ? Math.min(100, (latest.memory / memLimitBytes) * 100) : 0;
	$: inSwap = Boolean(latest?.swap);
	// Named only when the chat is on another size than the default.
	$: sizeName = size && !size.default ? size.display_name : '';
	$: detailLine = [sizeName, state === 'ready' || state === 'starting' ? resources : '']
		.filter(Boolean)
		.join(' · ');
</script>

{#if visible && state !== 'hidden'}
	<div class="relative">
		<button
			type="button"
			class="flex items-center gap-1.5 px-1.5 py-0.5 mr-0.5 rounded-md hover:bg-gray-50 dark:hover:bg-gray-850"
			on:click={toggle}
			title={statusLabel}
			aria-expanded={open}
			aria-haspopup="true"
		>
			{#if state === 'starting'}
				<span
					class="inline-block size-2.5 shrink-0 border-2 border-gray-400 border-t-transparent rounded-full animate-spin"
				></span>
			{:else if state === 'paused'}
				<span class="inline-block size-2.5 shrink-0 rounded-full bg-gray-400 dark:bg-gray-500"
				></span>
			{:else if state === 'degraded'}
				<span class="inline-block size-2.5 shrink-0 rounded-full bg-red-500"></span>
			{:else}
				<span class="tool-runner-dot inline-block size-2.5 shrink-0 rounded-full bg-emerald-500"
				></span>
			{/if}
			<div class="flex flex-col leading-tight min-w-0 text-left">
				<span
					class="text-xs font-medium whitespace-nowrap {state === 'degraded'
						? 'text-red-600 dark:text-red-400'
						: 'text-gray-700 dark:text-gray-200'}">{statusLabel}</span
				>
				{#if detailLine}
					<span class="text-[10px] text-gray-500 dark:text-gray-400 whitespace-nowrap"
						>{detailLine}</span
					>
				{/if}
			</div>
		</button>
		{#if open}
			<div
				class="absolute right-0 top-full mt-1 z-40 w-72 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-2.5 text-xs shadow"
			>
				{#if state === 'ready'}
					<div class="mb-1 text-gray-500">
						{$i18n.t('CPU')} ({fmtCpu(latest?.cpu ?? 0)}{cpuLimit ? ` / ${fmtCpu(cpuLimit)}` : ''}
						{$i18n.t('cores')})
					</div>
					<div class="h-2 w-full rounded bg-gray-200 dark:bg-gray-700">
						<div class="h-2 rounded bg-sky-500" style="width: {cpuPct}%"></div>
					</div>
					<div class="mt-2 mb-1 text-gray-500">
						{$i18n.t('Memory')} ({fmtMemGib(latest?.memory ?? 0)}{memLimitBytes
							? ` / ${fmtMemGib(memLimitBytes)}`
							: ''} GB)
					</div>
					<div class="h-2 w-full rounded bg-gray-200 dark:bg-gray-700">
						<div
							class="h-2 rounded {inSwap ? 'bg-red-500' : 'bg-sky-500'}"
							style="width: {memPct}%"
						></div>
					</div>
					<div class="mt-2.5 mb-1 text-gray-500">{$i18n.t('Memory, last minute')}</div>
					<div class="flex gap-0.5 h-8 items-end">
						{#each samples as s}
							<div
								class="flex-1 min-w-px {s.swap ? 'bg-red-500' : 'bg-sky-400'}"
								style="height: {memLimitBytes ? Math.max(8, (s.memory / memLimitBytes) * 100) : 8}%"
								title="{fmtMemGib(s.memory)} GB{s.swap ? ` · ${$i18n.t('swap')}` : ''}"
							></div>
						{/each}
					</div>
					{#if inSwap}
						<div class="mt-1 text-red-600 dark:text-red-400">
							{$i18n.t('Using disk swap')}
						</div>
					{/if}
				{/if}
				{#if sizes.length > 1}
					<div
						class="{state === 'ready'
							? 'mt-3 pt-2.5 border-t border-gray-100 dark:border-gray-800'
							: ''} mb-1.5 text-gray-500"
					>
						{$i18n.t('Runner size')}
					</div>
					<div class="flex flex-col gap-1" role="radiogroup" aria-label={$i18n.t('Runner size')}>
						{#each sizes as option}
							<button
								type="button"
								role="radio"
								aria-checked={option.type === size?.type}
								class="flex flex-col items-start rounded-md px-2 py-1.5 text-left border {option.type ===
								size?.type
									? 'border-sky-500 bg-sky-50 dark:bg-sky-950/40'
									: 'border-gray-100 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-850'} disabled:opacity-60"
								disabled={!!switching}
								on:click={() => pickSize(option)}
							>
								<span class="flex w-full items-center justify-between gap-2">
									<span class="font-medium text-gray-800 dark:text-gray-100"
										>{option.display_name}{switching === option.type ? '…' : ''}</span
									>
									<span class="text-gray-500 tabular-nums">{sizeLimits(option)}</span>
								</span>
								{#if option.description}
									<span class="text-[11px] text-gray-500">{option.description}</span>
								{/if}
							</button>
						{/each}
					</div>
					<div class="mt-1.5 text-[11px] text-gray-500">
						{$i18n.t('A larger size goes back to the default after its runner has been idle.')}
					</div>
				{:else if state !== 'ready'}
					<div class="text-gray-500">{statusLabel}</div>
				{/if}
			</div>
		{/if}
	</div>
{/if}

<style>
	@keyframes tool-runner-pulse {
		0%,
		100% {
			opacity: 1;
		}
		50% {
			opacity: 0.28;
		}
	}

	.tool-runner-dot {
		animation: tool-runner-pulse 3.6s ease-in-out infinite;
	}
</style>
