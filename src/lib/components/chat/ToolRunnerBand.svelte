<script lang="ts">
	import { getContext } from 'svelte';
	import { chatId, chatRunner, config, temporaryChatEnabled } from '$lib/stores';
	import { startToolRunner } from '$lib/apis/chats';

	const i18n = getContext('i18n');

	const CPU_CORES = 3;
	const MEM_GIB = 12;
	const MEM_BYTES = MEM_GIB * 1024 ** 3;

	type Sample = { t: number; cpu: number; memory: number; swap: boolean };

	let state: 'hidden' | 'starting' | 'ready' = 'hidden';
	let open = false;
	let samples: Sample[] = [];
	let lastCpuUsage: number | null = null;
	let lastCpuTime: number | null = null;
	let cpuLimit = CPU_CORES;
	let memLimitBytes = MEM_BYTES;
	let startedFor = '';
	let ensuring = false;

	$: enabled = Boolean($config?.features?.enable_tool_runner);
	$: visible = enabled && !$temporaryChatEnabled && $chatId && $chatId !== 'local';

	$: if (visible && $chatId && $chatId !== startedFor) {
		startedFor = $chatId;
		resetBand();
		state = 'starting';
		ensure($chatId);
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
		cpuLimit = CPU_CORES;
		memLimitBytes = MEM_BYTES;
	};

	const ensure = async (id: string) => {
		if (ensuring) return;
		ensuring = true;
		if (state !== 'ready') state = 'starting';
		try {
			const res = await startToolRunner(localStorage.token, id);
			if (id !== $chatId) return;
			if (res?.state === 'ready') state = 'ready';
			else if (res?.enabled === false) state = 'hidden';
			else if (state !== 'ready') state = 'starting';
		} catch {
			if (id === $chatId && state !== 'ready') state = 'starting';
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
		return Math.min(cpuLimit, Math.max(0, du / 1_000_000 / dt));
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
			swap: Number(metrics.memory_swap_current || 0) > 0
		};
		samples = [...samples.filter((s) => Date.now() - s.t < 60_000), next];
	};

	const applyLive = (row: { state?: string; metrics?: Record<string, any> | null }) => {
		if (row.state === 'ready') state = 'ready';
		else if (row.state === 'starting') {
			if (state === 'ready') open = false;
			state = 'starting';
		}
		if (row.metrics) applyMetrics(row.metrics);
	};

	const toggle = () => {
		if (state !== 'ready') return;
		open = !open;
	};

	const fmtCpu = (n: number) => {
		if (n >= 10) return n.toFixed(0);
		return n.toFixed(1).replace(/\.0$/, '');
	};

	const fmtMemGib = (bytes: number) => {
		const gb = bytes / 1024 ** 3;
		if (gb <= 0) return '0';
		if (gb >= 10) return gb.toFixed(0);
		if (gb >= 1) return gb.toFixed(1);
		return gb.toFixed(2);
	};

	$: latest = samples[samples.length - 1];
	$: memLimitGb = memLimitBytes / 1024 ** 3;
	$: resources = latest
		? `${fmtCpu(latest.cpu)} / ${fmtCpu(cpuLimit)} CPU - ${fmtMemGib(latest.memory)} / ${fmtMemGib(memLimitBytes)} GB Memory`
		: `0 / ${fmtCpu(cpuLimit)} CPU - 0 / ${fmtMemGib(memLimitBytes)} GB Memory`;
	$: statusLabel =
		state === 'ready'
			? $i18n.t('Weather skills runner ready')
			: $i18n.t('Weather skills runner starting');
	$: cpuPct = latest && cpuLimit ? Math.min(100, (latest.cpu / cpuLimit) * 100) : 0;
	$: memPct = latest && memLimitBytes ? Math.min(100, (latest.memory / memLimitBytes) * 100) : 0;
	$: inSwap = Boolean(latest?.swap);
</script>

{#if visible && state !== 'hidden'}
	<div class="relative">
		<button
			type="button"
			class="flex items-center gap-1.5 px-1.5 py-0.5 mr-0.5 rounded-md {state === 'ready'
				? 'hover:bg-gray-50 dark:hover:bg-gray-850'
				: ''}"
			on:click={toggle}
			title={statusLabel}
			aria-expanded={open}
			aria-haspopup="true"
		>
			{#if state === 'starting'}
				<span
					class="inline-block size-2.5 shrink-0 border-2 border-gray-400 border-t-transparent rounded-full animate-spin"
				></span>
			{:else}
				<span class="tool-runner-dot inline-block size-2.5 shrink-0 rounded-full bg-emerald-500"
				></span>
			{/if}
			<div class="flex flex-col leading-tight min-w-0 text-left">
				<span class="text-xs font-medium text-gray-700 dark:text-gray-200 whitespace-nowrap"
					>{statusLabel}</span
				>
				<span class="text-[10px] text-gray-500 dark:text-gray-400 whitespace-nowrap">{resources}</span
				>
			</div>
		</button>
		{#if open && state === 'ready'}
			<div
				class="absolute right-0 top-full mt-1 z-40 w-64 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-2.5 text-xs shadow"
			>
				<div class="mb-1 text-gray-500">
					{$i18n.t('CPU')} ({fmtCpu(latest?.cpu ?? 0)} / {fmtCpu(cpuLimit)}
					{$i18n.t('cores')})
				</div>
				<div class="h-2 w-full rounded bg-gray-200 dark:bg-gray-700">
					<div class="h-2 rounded bg-sky-500" style="width: {cpuPct}%"></div>
				</div>
				<div class="mt-2 mb-1 text-gray-500">
					{$i18n.t('Memory')} ({fmtMemGib(latest?.memory ?? 0)} / {fmtMemGib(memLimitBytes)} GB)
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
							style="height: {Math.max(8, (s.memory / memLimitBytes) * 100)}%"
							title="{fmtMemGib(s.memory)} GB{s.swap ? ` · ${$i18n.t('swap')}` : ''}"
						></div>
					{/each}
				</div>
				{#if inSwap}
					<div class="mt-1 text-red-600 dark:text-red-400">
						{$i18n.t('Using disk swap')}
					</div>
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
