<script lang="ts">
	// An HTML artifact (for example a Plotly figure) in a sandboxed iframe.
	//
	// No allow-same-origin: the page gets its own opaque origin, so its scripts
	// cannot read this app's storage or cookies or call its API as the user.
	// The view route sends the same sandbox as a CSP header. allow-downloads
	// keeps Plotly's "download plot as PNG" button working.
	export let src = '';
	export let title = 'Interactive figure';
	export let className = '';
	export let lazy = true;
</script>

<iframe
	{src}
	{title}
	class="block w-full border-0 bg-white {className}"
	sandbox="allow-scripts allow-downloads"
	referrerpolicy="no-referrer"
	loading={lazy ? 'lazy' : 'eager'}
/>
