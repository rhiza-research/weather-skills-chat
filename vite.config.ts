import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig, type Plugin } from 'vite';

import { viteStaticCopy } from 'vite-plugin-static-copy';

// /** @type {import('vite').Plugin} */
// const viteServerConfig = {
// 	name: 'log-request-middleware',
// 	configureServer(server) {
// 		server.middlewares.use((req, res, next) => {
// 			res.setHeader('Access-Control-Allow-Origin', '*');
// 			res.setHeader('Access-Control-Allow-Methods', 'GET');
// 			res.setHeader('Cross-Origin-Opener-Policy', 'same-origin');
// 			res.setHeader('Cross-Origin-Embedder-Policy', 'require-corp');
// 			next();
// 		});
// 	}
// };

// i18n sets returnEmptyString: false, so an empty value already behaves as a missing one.
// The source files keep them as the list of strings still to translate.
const stripEmptyTranslations: Plugin = {
	name: 'strip-empty-translations',
	enforce: 'pre',
	transform(code, id) {
		if (!/\/src\/lib\/i18n\/locales\/[^/]+\/translation\.json$/.test(id)) return null;
		const entries = Object.entries(JSON.parse(code)).filter(([, value]) => value !== '');
		return { code: JSON.stringify(Object.fromEntries(entries)), map: null };
	}
};

export default defineConfig({
	plugins: [
		stripEmptyTranslations,
		sveltekit(),
		viteStaticCopy({
			targets: [
				{
					src: 'node_modules/onnxruntime-web/dist/*.jsep.*',

					dest: 'wasm'
				}
			]
		})
	],
	define: {
		APP_VERSION: JSON.stringify(process.env.npm_package_version),
		APP_BUILD_HASH: JSON.stringify(process.env.APP_BUILD_HASH || 'dev-build')
	},
	build: {
		sourcemap: false
	},
	worker: {
		format: 'es'
	},
	test: {
		include: ['src/**/*.test.ts'],
		passWithNoTests: true
	}
});
