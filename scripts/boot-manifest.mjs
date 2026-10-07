// Writes the files each first page needs, with their compressed sizes, into build/index.html.
// The inline boot script in src/app.html preloads them and measures download progress against them.
import { existsSync, readdirSync, readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { brotliCompressSync, constants } from 'node:zlib';

const kit = path.resolve('.svelte-kit');
const build = path.resolve('build');
const manifest = JSON.parse(readFileSync(path.join(kit, 'output/client/.vite/manifest.json'), 'utf8'));
const nodesDir = path.join(kit, 'generated/client-optimized/nodes');

const ROUTES = {
	root: ['src/routes/+layout.svelte', 'src/routes/+error.svelte'],
	auth: ['src/routes/auth/+page.svelte'],
	app: ['src/routes/(app)/+layout.svelte'],
	home: ['src/routes/(app)/+page.svelte'],
	chat: ['src/routes/(app)/c/[id]/+page.svelte']
};

const nodeKey = (file) => `.svelte-kit/generated/client-optimized/nodes/${file}`;
const nodeFor = {};
for (const file of readdirSync(nodesDir)) {
	const source = readFileSync(path.join(nodesDir, file), 'utf8');
	for (const [name, components] of Object.entries(ROUTES)) {
		if (components.some((component) => source.includes(`/${component}"`))) {
			(nodeFor[name] ??= []).push(nodeKey(file));
		}
	}
}
for (const [name, components] of Object.entries(ROUTES)) {
	if ((nodeFor[name]?.length ?? 0) !== components.length) {
		throw new Error(`boot-manifest: expected ${components.length} node(s) for ${name}, found ${nodeFor[name]?.length ?? 0}`);
	}
}

const collect = (keys, into = new Set()) => {
	for (const key of keys) {
		const chunk = manifest[key];
		if (!chunk || into.has(chunk.file)) continue;
		into.add(chunk.file);
		for (const css of chunk.css ?? []) into.add(css);
		collect(chunk.imports ?? [], into);
	}
	return into;
};

const entryKeys = Object.keys(manifest).filter(
	(key) => manifest[key].isEntry && /entry\/(start|app)$/.test(manifest[key].name ?? '')
);
if (entryKeys.length !== 2) throw new Error('boot-manifest: SvelteKit entry chunks not found');
const entry = collect(entryKeys);

const files = [];
const index = new Map();
const sizeOf = (file) => {
	const full = path.join(build, file);
	const raw = readFileSync(full);
	const br = brotliCompressSync(raw, {
		params: {
			[constants.BROTLI_PARAM_QUALITY]: 11,
			[constants.BROTLI_PARAM_MODE]: constants.BROTLI_MODE_TEXT
		}
	});
	return Math.min(raw.length, br.length);
};
const idOf = (file) => {
	if (!index.has(file)) {
		index.set(file, files.length);
		files.push([`/${file}`, sizeOf(file)]);
	}
	return index.get(file);
};

// Loaded with import() as soon as a signed-in page mounts.
const SESSION_MODULES = ['node_modules/socket.io-client/build/esm/index.js'];
for (const key of SESSION_MODULES) {
	if (!manifest[key]) throw new Error(`boot-manifest: ${key} not in the Vite manifest`);
}

const sets = { entry: [...entry].map(idOf) };
for (const name of Object.keys(ROUTES)) {
	sets[name] = [...collect(nodeFor[name])].filter((file) => !entry.has(file)).map(idOf);
}
sets.session = [...collect(SESSION_MODULES)].filter((file) => !entry.has(file)).map(idOf);

const appSegments = readdirSync(path.resolve('src/routes/(app)'), { withFileTypes: true })
	.filter((dirent) => dirent.isDirectory())
	.map((dirent) => dirent.name);

const locales = {};
for (const [key, chunk] of Object.entries(manifest)) {
	const match = key.match(/^src\/lib\/i18n\/locales\/([^/]+)\/translation\.json$/);
	if (match) locales[match[1]] = `/${chunk.file}`;
}
if (!locales['en-US']) throw new Error('boot-manifest: en-US translation chunk not found');

const splashFile = path.resolve('static/static/splash.png');
if (!existsSync(splashFile)) throw new Error('boot-manifest: static/static/splash.png not found');
const splashUri = `data:image/png;base64,${readFileSync(splashFile).toString('base64')}`;

const data = JSON.stringify({ files, sets, appSegments, locales });
const placeholder = '<script id="wsc-boot-routes" type="application/json">null</script>';
const html = path.join(build, 'index.html');
if (!existsSync(html)) throw new Error('boot-manifest: build/index.html not found');
const page = readFileSync(html, 'utf8');
if (!page.includes(placeholder)) throw new Error('boot-manifest: placeholder missing from index.html');
const splashSrc = 'src="/static/splash.png"';
if (!page.includes(splashSrc)) throw new Error('boot-manifest: splash <img> src missing from index.html');
writeFileSync(
	html,
	page.replace(placeholder, placeholder.replace('null', data)).replace(splashSrc, `src="${splashUri}"`)
);

const kb = (ids) => (ids.reduce((sum, id) => sum + files[id][1], 0) / 1024).toFixed(0);
console.log(
	`boot-manifest: ${Object.entries(sets)
		.map(([name, ids]) => `${name} ${ids.length} files ${kb(ids)} KB`)
		.join(', ')}; splash ${(splashUri.length / 1024).toFixed(1)} KB inlined`
);
