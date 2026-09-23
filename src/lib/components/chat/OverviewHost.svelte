<script lang="ts">
	import { SvelteFlowProvider } from '@xyflow/svelte';
	import Overview from './Overview.svelte';

	export let history;
</script>

<SvelteFlowProvider>
	<Overview {history} on:nodeclick on:close />
</SvelteFlowProvider>
