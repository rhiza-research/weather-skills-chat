import { describe, expect, it } from 'vitest';
import { safeLinkUrl } from './index';

describe('safeLinkUrl', () => {
	it('keeps http, https, mailto and relative links', () => {
		for (const url of ['https://a.org/x', 'http://a.org', 'mailto:a@b.org', '/c/1', '#x', 'notes.md']) {
			expect(safeLinkUrl(url)).toBe(url);
		}
	});

	it('drops links that could run script', () => {
		for (const url of [
			'javascript:alert(1)',
			'JavaScript:alert(1)',
			' javascript:alert(1)',
			'java\tscript:alert(1)',
			// a file item opens `${url}/content`; the suffix must not rescue the scheme
			'javascript:alert(1)///content',
			'data:text/html,<script>alert(1)</script>',
			'vbscript:x'
		]) {
			expect(safeLinkUrl(url)).toBeUndefined();
		}
	});
});
