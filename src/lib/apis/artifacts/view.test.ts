import { describe, expect, it } from 'vitest';
import { getArtifactViewUrl, isHtmlArtifact } from './index';

describe('getArtifactViewUrl', () => {
	it('keeps folders as path segments and encodes each one', () => {
		const url = getArtifactViewUrl('chat-1', 'plots/sst 2017#a.html');
		expect(url.endsWith('/chats/chat-1/artifacts/view/plots/sst%202017%23a.html')).toBe(true);
	});
});

describe('isHtmlArtifact', () => {
	it('matches .html and .htm only', () => {
		expect(isHtmlArtifact('plots/sst.html')).toBe(true);
		expect(isHtmlArtifact('PLOT.HTM')).toBe(true);
		expect(isHtmlArtifact('plot.png')).toBe(false);
		expect(isHtmlArtifact('notes.html.txt')).toBe(false);
		expect(isHtmlArtifact(null)).toBe(false);
	});
});
