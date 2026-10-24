import { describe, expect, it } from 'vitest';

import { toolUsageLine } from './toolUsage';

describe('toolUsageLine', () => {
	it('shows CPU time, peak memory, and run time', () => {
		expect(toolUsageLine({ cpu_seconds: 1.5, memory_mb: 512.5, run_seconds: 2.25 })).toBe(
			'CPU time 1.5 s - Peak memory 513 MB - Run time 2.3 s'
		);
	});

	it('shows GB from 1024 MB and whole seconds from 10 s', () => {
		expect(toolUsageLine({ cpu_seconds: 42.4, memory_mb: 3584, run_seconds: 60 })).toBe(
			'CPU time 42 s - Peak memory 3.5 GB - Run time 60 s'
		);
	});

	it('shows zeros', () => {
		expect(toolUsageLine({ cpu_seconds: 0, memory_mb: 0, run_seconds: 0 })).toBe(
			'CPU time 0 s - Peak memory 0 MB - Run time 0 s'
		);
	});

	it('is empty when the result has no complete usage', () => {
		expect(toolUsageLine(undefined)).toBe('');
		expect(toolUsageLine(null)).toBe('');
		expect(toolUsageLine('1.5')).toBe('');
		expect(toolUsageLine({ cpu_seconds: 1.5, memory_mb: 512 })).toBe('');
		expect(toolUsageLine({ cpu_seconds: '1.5', memory_mb: 512, run_seconds: 2 })).toBe('');
		expect(toolUsageLine({ cpu_seconds: -1, memory_mb: 512, run_seconds: 2 })).toBe('');
		expect(toolUsageLine({ cpu_seconds: NaN, memory_mb: 512, run_seconds: 2 })).toBe('');
	});
});
