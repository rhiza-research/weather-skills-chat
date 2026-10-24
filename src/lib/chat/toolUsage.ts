// The usage line under a tool runner skill's output, from the result's
// tool_resource_usage (see skill_k8s_sandbox.py).

import { fmtMemGib } from './runnerResources';

const fmtSeconds = (n: number) => {
	if (n >= 10) return n.toFixed(0);
	return n.toFixed(1).replace(/\.0$/, '');
};

const fmtMemMb = (mb: number) =>
	mb >= 1024 ? `${fmtMemGib(mb * 1024 ** 2)} GB` : `${Math.round(mb)} MB`;

const isAmount = (value: unknown): value is number =>
	typeof value === 'number' && Number.isFinite(value) && value >= 0;

/** "CPU time … - Peak memory … - Run time …", or '' when the result has no complete usage. */
export const toolUsageLine = (usage: unknown): string => {
	if (!usage || typeof usage !== 'object') return '';
	const { cpu_seconds, memory_mb, run_seconds } = usage as Record<string, unknown>;
	if (!isAmount(cpu_seconds) || !isAmount(memory_mb) || !isAmount(run_seconds)) return '';
	return `CPU time ${fmtSeconds(cpu_seconds)} s - Peak memory ${fmtMemMb(memory_mb)} - Run time ${fmtSeconds(run_seconds)} s`;
};
