<script lang="ts">
	import SettingRow from './SettingRow.svelte';

	export let label = '';
	export let tooltip = '';
	export let text = '';
</script>

<SettingRow {label} {tooltip}>
	<button class="py-1 px-3 text-xs transition shrink-0 outline-hidden" type="button" on:click>
		{text}
	</button>
</SettingRow>
