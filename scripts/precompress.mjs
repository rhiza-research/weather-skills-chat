import os from 'node:os';
import { readdirSync, statSync } from 'node:fs';
import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { promisify } from 'node:util';
import { brotliCompress, constants } from 'node:zlib';

// Async zlib runs on libuv's thread pool, which has 4 threads unless set before first use.
process.env.UV_THREADPOOL_SIZE = String(os.availableParallelism());
const compress = promisify(brotliCompress);

const root = path.resolve('build');
const extensions = new Set(['.js', '.mjs', '.css', '.html', '.json', '.svg', '.xml', '.txt']);
const minBytes = 256;

const files = [];
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
		files.push(full);
	}
};

walk(root);
await Promise.all(
	files.map(async (full) => {
		const raw = await readFile(full);
		const compressed = await compress(raw, {
			params: {
				[constants.BROTLI_PARAM_QUALITY]: 11,
				[constants.BROTLI_PARAM_MODE]: constants.BROTLI_MODE_TEXT
			}
		});
		if (compressed.length < raw.length) {
			await writeFile(`${full}.br`, compressed);
		}
	})
);
console.log(`precompressed brotli assets in ${root}`);
