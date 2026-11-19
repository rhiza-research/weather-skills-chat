import { describe, expect, it } from 'vitest';
import { safeLinkUrl } from './index';

describe('safeLinkUrl', () => {
	it('keeps http, https, mailto, tel and relative links', () => {
		for (const url of [
			'https://a.org/x',
			'http://a.org',
			'mailto:a@b.org',
			'tel:123',
			'/c/1',
			'#x'
		]) {
			expect(safeLinkUrl(url)).toBe(url);
		}
	});

	it('drops other schemes', () => {
		for (const url of [
			'javascript:alert(1)',
			'JavaScript:alert(1)',
			'data:text/html,x',
			'vbscript:x'
		]) {
			expect(safeLinkUrl(url)).toBeUndefined();
		}
	});
});
