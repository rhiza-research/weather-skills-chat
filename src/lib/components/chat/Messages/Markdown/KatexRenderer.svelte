<script lang="ts">
	export let content: string;
	export let displayMode: boolean = false;

	let html = '';
	let request = 0;

	const render = async (nextContent: string, nextDisplayMode: boolean) => {
		const current = ++request;
		const katex = (await import('katex')).default;
		await import('katex/contrib/mhchem');
		await import('katex/dist/katex.min.css');
		if (current !== request) {
			return;
		}
		html = katex.renderToString(nextContent, { displayMode: nextDisplayMode, throwOnError: false });
	};

	$: render(content, displayMode);
</script>

{@html html}
