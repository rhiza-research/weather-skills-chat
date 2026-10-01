import { readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { brotliCompressSync, constants } from 'node:zlib';

const root = path.resolve('build');
const extensions = new Set(['.js', '.mjs', '.css', '.html', '.json', '.svg', '.xml', '.txt']);
const minBytes = 256;

const walk = (dir) => {
	for (const entry of readdirSync(dir, { withFileTypes: true })) {
		const full = path.join(dir, entry.name);
		if (entry.isDirectory()) {
			walk(full);
			continue;
		}
		const ext = path.extname(entry.name).toLowerCase();
		if (!extensions.has(ext) || entry.name.endsWith('.br')) {
			continue;
		}
		if (statSync(full).size < minBytes) {
			continue;
		}
		const raw = readFileSync(full);
		const compressed = brotliCompressSync(raw, {
			params: {
				[constants.BROTLI_PARAM_QUALITY]: 11,
				[constants.BROTLI_PARAM_MODE]: constants.BROTLI_MODE_TEXT
			}
		});
		if (compressed.length < raw.length) {
			writeFileSync(`${full}.br`, compressed);
		}
	}
};

walk(root);
console.log(`precompressed brotli assets in ${root}`);
