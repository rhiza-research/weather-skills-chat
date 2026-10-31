import { describe, expect, it } from 'vitest';
import { DOT_MAX_AGE_S, describeSchedule, sortTasks, taskDot } from './scheduledTasks';

const NOW = 1_800_000_000;

const task = (id: string, run: object | null = null, extra: object = {}) => ({
	id,
	name: id,
	created_at: 0,
	seen_run_id: null,
	last_run: run ? { id: `${id}-run`, started_at: NOW - 60, finished_at: NOW - 30, ...run } : null,
	...extra
});

describe('taskDot', () => {
	it('pulses grey while the last run is going', () => {
		expect(taskDot(task('a', { status: 'running', finished_at: null }), NOW)).toBe('running');
	});

	it('shows how an unseen run ended', () => {
		for (const status of ['success', 'failure', 'unknown', 'error']) {
			expect(taskDot(task('a', { status }), NOW)).toBe(status);
		}
	});

	it('shows no dot for a run the user stopped', () => {
		expect(taskDot(task('a', { status: 'stopped' }), NOW)).toBeNull();
	});

	it('clears once the run is seen', () => {
		expect(taskDot(task('a', { status: 'success' }, { seen_run_id: 'a-run' }), NOW)).toBeNull();
	});

	it('shows no dot for a run that ended more than a week ago', () => {
		const old = { status: 'failure', finished_at: NOW - DOT_MAX_AGE_S - 1 };
		expect(taskDot(task('a', old), NOW)).toBeNull();
	});

	it('shows no dot before the first run', () => {
		expect(taskDot(task('a'), NOW)).toBeNull();
	});
});

describe('sortTasks', () => {
	const tasks = [
		task('beta', { status: 'success', started_at: NOW - 500 }, { created_at: 3, updated_at: 4 }),
		task('alpha', null, { created_at: 1, updated_at: 5 }),
		task('gamma', { status: 'success', started_at: NOW - 100 }, { created_at: 2, updated_at: 2 })
	];

	it('puts the most recently run first, and tasks never run last', () => {
		expect(sortTasks(tasks, 'recent').map((t) => t.id)).toEqual(['gamma', 'beta', 'alpha']);
	});

	it('sorts by name', () => {
		expect(sortTasks(tasks, 'name').map((t) => t.id)).toEqual(['alpha', 'beta', 'gamma']);
	});

	it('puts the newest task first', () => {
		expect(sortTasks(tasks, 'created').map((t) => t.id)).toEqual(['beta', 'gamma', 'alpha']);
	});

	it('puts the most recently edited first', () => {
		expect(sortTasks(tasks, 'updated').map((t) => t.id)).toEqual(['alpha', 'beta', 'gamma']);
	});
});

describe('describeSchedule', () => {
	it('reads cron as English in UTC', () => {
		expect(describeSchedule('0 6 * * 1,4')).toBe(
			'At 06:00 AM, only on Monday and Thursday (UTC)'
		);
		expect(describeSchedule('30 18 * * 1-5')).toBe(
			'At 06:30 PM, Monday through Friday (UTC)'
		);
	});

	it('reads Sunday as 0 or 7, as the scheduler does', () => {
		expect(describeSchedule('0 9 * * 0')).toContain('Sunday');
		expect(describeSchedule('0 9 * * 7')).toContain('Sunday');
	});

	it('says when there is no schedule, and falls back to the cron it cannot read', () => {
		expect(describeSchedule(null)).toBe('Runs only when started');
		expect(describeSchedule('not cron')).toBe('not cron');
	});
});
