import { describe, expect, it } from 'vitest';

import { fmtCpu, fmtMemGib, runnerResourcesLine } from './runnerResources';

const GiB = 1024 ** 3;

describe('runnerResourcesLine', () => {
	it('is empty until the runner has reported its limits', () => {
		expect(runnerResourcesLine(undefined, null, null)).toBe('');
		expect(runnerResourcesLine({ cpu: 0.5, memory: GiB }, 3, null)).toBe('');
		expect(runnerResourcesLine({ cpu: 0.5, memory: GiB }, null, 8 * GiB)).toBe('');
	});

	it('shows the reported limits', () => {
		expect(runnerResourcesLine({ cpu: 1.25, memory: 2.5 * GiB }, 3, 8 * GiB)).toBe(
			'1.3 / 3 CPU - 2.5 / 8.0 GB Memory'
		);
	});

	it('shows zero usage before the first sample', () => {
		expect(runnerResourcesLine(undefined, 3, 8 * GiB)).toBe('0 / 3 CPU - 0 / 8.0 GB Memory');
	});
});

describe('formatting', () => {
	it('formats cores and GiB', () => {
		expect(fmtCpu(3)).toBe('3');
		expect(fmtCpu(12)).toBe('12');
		expect(fmtMemGib(0)).toBe('0');
		expect(fmtMemGib(0.5 * GiB)).toBe('0.50');
		expect(fmtMemGib(12 * GiB)).toBe('12');
	});
});
