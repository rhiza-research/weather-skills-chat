<script>
	import OrganizationMembership from '$lib/components/admin/Users/OrganizationMembership.svelte';
	import { getContext } from 'svelte';

	const i18n = getContext('i18n');
</script>

<OrganizationMembership
	title={$i18n.t('Platform organization membership')}
	organizationId="platform"
/>
