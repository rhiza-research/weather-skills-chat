// Text for the tool runner band. Limits come only from the runner's own
// metrics (the daemon reads them from the pod cgroup); there is no built-in
// default, so nothing is shown until the runner has reported them.

export const fmtCpu = (n: number) => {
	if (n >= 10) return n.toFixed(0);
	return n.toFixed(1).replace(/\.0$/, '');
};

export const fmtMemGib = (bytes: number) => {
	const gb = bytes / 1024 ** 3;
	if (gb <= 0) return '0';
	if (gb >= 10) return gb.toFixed(0);
	if (gb >= 1) return gb.toFixed(1);
	return gb.toFixed(2);
};

/** "used / limit CPU - used / limit GB Memory", or '' while the limits are unknown. */
export const runnerResourcesLine = (
	latest: { cpu: number; memory: number } | undefined,
	cpuLimit: number | null,
	memLimitBytes: number | null
): string => {
	if (!cpuLimit || !memLimitBytes) return '';
	const cpu = fmtCpu(latest?.cpu ?? 0);
	const memory = fmtMemGib(latest?.memory ?? 0);
	return `${cpu} / ${fmtCpu(cpuLimit)} CPU - ${memory} / ${fmtMemGib(memLimitBytes)} GB Memory`;
};
