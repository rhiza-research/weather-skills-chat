import { describe, expect, it } from 'vitest';
import {
	COMPACTION_TIMEOUT_MS,
	compactionRunning,
	contextShown,
	runningCompaction
} from './compaction';

const history = (reply: any, current: any = {}) => ({
	currentId: 'a2',
	messages: {
		a1: { id: 'a1', parentId: null, role: 'assistant', ...reply },
		u2: { id: 'u2', parentId: 'a1', role: 'user' },
		a2: { id: 'a2', parentId: 'u2', role: 'assistant', ...current }
	}
});

describe('compactionRunning', () => {
	it('stops counting after the timeout', () => {
		const now = 1_000_000_000_000;
		const started = now / 1000;
		expect(compactionRunning({ status: 'running', started_at: started }, now)).toBe(true);
		expect(
			compactionRunning(
				{ status: 'running', started_at: started },
				now + COMPACTION_TIMEOUT_MS + 1
			)
		).toBe(false);
		expect(compactionRunning({ status: 'done', started_at: started }, now)).toBe(false);
	});
});

describe('runningCompaction', () => {
	it('finds one earlier on the branch', () => {
		const running = { status: 'running', started_at: Date.now() / 1000 };
		expect(runningCompaction(history({ compaction: running }))).toBe(running);
		expect(runningCompaction(history({}))).toBeNull();
	});
});

describe('contextShown', () => {
	it('shows the estimate until a later reply reports usage', () => {
		const compaction = { status: 'done', context_estimate: 30, context_window: 200 };
		expect(contextShown(history({ compaction }))).toEqual({
			used: 30,
			window: 200,
			estimate: true
		});
		const later = history(
			{ compaction },
			{ usage: { context_used: 50, context_window: 200 } }
		);
		expect(contextShown(later)).toEqual({ used: 50, window: 200, estimate: false });
	});

	it('prefers the estimate on the reply that was compacted', () => {
		const current = {
			usage: { context_used: 190, context_window: 200 },
			compaction: { status: 'done', context_estimate: 20, context_window: 200 }
		};
		expect(contextShown(history({}, current))?.used).toBe(20);
	});

	it('is null without usage', () => {
		expect(contextShown(history({}))).toBeNull();
	});
});
