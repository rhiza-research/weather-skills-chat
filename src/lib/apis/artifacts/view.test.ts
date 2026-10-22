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

import { artifactHrefForChat, artifactPathForChat } from './index';

describe('artifactPathForChat', () => {
	it('turns a relative markdown href into a sandbox path', () => {
		expect(artifactPathForChat('./plots/sst%202017.html', 'chat-1')).toBe('plots/sst 2017.html');
		expect(artifactPathForChat('plots/sst.html#top', 'chat-1')).toBe('plots/sst.html');
	});

	it('ignores absolute, escaping and temporary-chat links', () => {
		expect(artifactPathForChat('https://example.com/x.html', 'chat-1')).toBeNull();
		expect(artifactPathForChat('/static/x.html', 'chat-1')).toBeNull();
		expect(artifactPathForChat('../x.html', 'chat-1')).toBeNull();
		expect(artifactPathForChat('x.html', 'local')).toBeNull();
	});

	it('still gives the content URL for other files', () => {
		expect(artifactHrefForChat('data.csv', 'chat-1')).toMatch(
			/\/chats\/chat-1\/artifacts\/content\?path=data\.csv$/
		);
	});
});
