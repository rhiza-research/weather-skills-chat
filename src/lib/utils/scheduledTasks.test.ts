import { describe, expect, it } from 'vitest';
import { DOT_MAX_AGE_S, sortTasks, taskDot } from './scheduledTasks';

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
		task('beta', { status: 'success', started_at: NOW - 500 }, { created_at: 3 }),
		task('alpha', null, { created_at: 1 }),
		task('gamma', { status: 'success', started_at: NOW - 100 }, { created_at: 2 })
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
});
