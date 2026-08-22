// Helper function to find the end of a details block.
// Details are not intentionally nested in chat content. If a sibling <details
// appears while the current block is still open, treat that as the end so
// unclosed reasoning tags (common with GPT tool calls) do not swallow the rest
// of the message as raw HTML.
function findDetailsBlockEnd(src: string, openLength: number): { end: number; closed: boolean } {
	let depth = 1;
	let index = openLength;
	while (depth > 0 && index < src.length) {
		if (src.startsWith('<details', index)) {
			if (depth === 1) {
				return { end: index, closed: false };
			}
			depth++;
			index += 8;
			continue;
		}
		if (src.startsWith('</details>', index)) {
			depth--;
			index += '</details>'.length;
			if (depth === 0) {
				return { end: index, closed: true };
			}
			continue;
		}
		index++;
	}
	return { end: index, closed: depth === 0 };
}

// Function to parse attributes from tag
function parseAttributes(tag: string): { [key: string]: string } {
	const attributes: { [key: string]: string } = {};
	const attrRegex = /(\w+)="(.*?)"/g;
	let match;
	while ((match = attrRegex.exec(tag)) !== null) {
		attributes[match[1]] = match[2];
	}
	return attributes;
}

function detailsTokenizer(src: string) {
	// Updated regex to capture attributes inside <details>
	const detailsRegex = /^<details(\s+[^>]*)?>\n/;
	const summaryRegex = /^<summary>(.*?)<\/summary>\n/;

	const detailsMatch = detailsRegex.exec(src);
	if (detailsMatch) {
		const detailsTag = detailsMatch[0];
		const { end: endIndex, closed } = findDetailsBlockEnd(src, detailsTag.length);
		if (endIndex <= detailsTag.length) return;

		const fullMatch = src.slice(0, endIndex);
		const attributes = parseAttributes(detailsTag); // Parse attributes from <details>

		let content = closed
			? fullMatch.slice(detailsTag.length, -'</details>'.length).trim()
			: fullMatch.slice(detailsTag.length).trim();
		let summary = '';

		const summaryMatch = summaryRegex.exec(content);
		if (summaryMatch) {
			summary = summaryMatch[1].trim();
			content = content.slice(summaryMatch[0].length).trim();
		}

		return {
			type: 'details',
			raw: fullMatch,
			summary: summary,
			text: content,
			attributes: attributes // Include extracted attributes from <details>
		};
	}
}

function detailsStart(src: string) {
	const match = src.match(/<details(?:\s|>)/);
	return match ? match.index : -1;
}

function detailsRenderer(token: any) {
	const attributesString = token.attributes
		? Object.entries(token.attributes)
				.map(([key, value]) => `${key}="${value}"`)
				.join(' ')
		: '';

	return `<details ${attributesString}>
  ${token.summary ? `<summary>${token.summary}</summary>` : ''}
  ${token.text}
  </details>`;
}

// Extension wrapper function
function detailsExtension() {
	return {
		name: 'details',
		level: 'block',
		start: detailsStart,
		tokenizer: detailsTokenizer,
		renderer: detailsRenderer
	};
}

export default function (options = {}) {
	return {
		extensions: [detailsExtension(options)]
	};
}
