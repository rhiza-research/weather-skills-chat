import { describe, expect, it } from 'vitest';

import { formatToolArgValue, toolArgRows, toolCallHead } from './toolArgs';

describe('toolCallHead', () => {
	it('names the tool and, for skill calls, the script', () => {
		expect(toolCallHead('plot', { script: 'plot.py', argv: [] })).toBe('plot plot.py');
		expect(toolCallHead('plot', { argv: ['-i', 'a.zarr'] })).toBe('plot');
		expect(toolCallHead('run', { script: 'x = 1' })).toBe('run');
		expect(toolCallHead('', null)).toBe('tool');
	});
});

describe('formatToolArgValue', () => {
	it('pretty-prints a JSON object string', () => {
		expect(formatToolArgValue('{"data":[{"uid":"0"}]}')).toEqual({
			text: '{\n  "data": [\n    {\n      "uid": "0"\n    }\n  ]\n}',
			lang: 'json'
		});
	});

	it('keeps Jsonnet and other non-JSON strings as written, newlines included', () => {
		const jsonnet = 'local c = 1;\n{\n  a: c,\n}';
		expect(formatToolArgValue(jsonnet)).toEqual({ text: jsonnet, lang: '' });
	});

	it('does not turn number-like or quoted strings into JSON', () => {
		expect(formatToolArgValue('2024-01-01')).toEqual({
			text: '2024-01-01',
			lang: ''
		});
		expect(formatToolArgValue('42')).toEqual({ text: '42', lang: '' });
		expect(formatToolArgValue('"hi"')).toEqual({ text: '"hi"', lang: '' });
	});

	it('shows empty strings, null, numbers and objects', () => {
		expect(formatToolArgValue('').text).toBe('""');
		expect(formatToolArgValue(null).text).toBe('null');
		expect(formatToolArgValue(3).text).toBe('3');
		expect(formatToolArgValue({ a: 1 })).toEqual({
			text: '{\n  "a": 1\n}',
			lang: 'json'
		});
	});

	it('keeps markup as plain text', () => {
		expect(formatToolArgValue('<img src=x onerror=alert(1)>').text).toBe(
			'<img src=x onerror=alert(1)>'
		);
	});
});

describe('toolArgRows', () => {
	it('pairs skill argv flags with their values', () => {
		const rows = toolArgRows({
			script: 'plot.py',
			argv: [
				'-i',
				'rain.zarr',
				'--spec',
				'{"layout":{}}',
				'--animate',
				'--bbox=5/33/-4.7/41',
				'extra'
			],
			env_secrets: ['NAME'],
			timeout: 600,
			display: 'Plotting'
		});
		expect(rows.map((r) => [r.key, r.value, r.multiline])).toEqual([
			['-i', 'rain.zarr', false],
			['--spec', '{\n  "layout": {}\n}', true],
			['--animate', '', false],
			['--bbox', '5/33/-4.7/41', false],
			['', 'extra', false]
		]);
	});

	it('takes a negative number after a flag as its value', () => {
		expect(toolArgRows({ argv: ['--lat', '-1.3'] }).map((r) => [r.key, r.value])).toEqual([
			['--lat', '-1.3']
		]);
	});

	it('lists object arguments one per row, without display', () => {
		const rows = toolArgRows({ path: 'a.png', display: 'Showing a.png', n: 2 });
		expect(rows.map((r) => [r.key, r.value])).toEqual([
			['path', 'a.png'],
			['n', '2']
		]);
	});

	it('handles arrays, scalars and no arguments', () => {
		expect(toolArgRows(['a', 1]).map((r) => r.value)).toEqual(['a', '1']);
		expect(toolArgRows('just text')).toEqual([
			{ key: '', value: 'just text', lang: '', multiline: false }
		]);
		expect(toolArgRows('')).toEqual([]);
		expect(toolArgRows({})).toEqual([]);
	});
});
