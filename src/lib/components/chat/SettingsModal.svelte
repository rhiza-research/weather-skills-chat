<script lang="ts">
	import Modal from '../common/Modal.svelte';
	import UserSettings from './UserSettings.svelte';

	export let show = false;
</script>

<Modal size="xl" bind:show>
	<UserSettings
		layout="modal"
		on:close={() => {
			show = false;
		}}
	/>
</Modal>
