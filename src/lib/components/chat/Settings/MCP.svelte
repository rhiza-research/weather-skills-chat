<script lang="ts">
	import { getContext, onMount } from 'svelte';
	import { toast } from 'svelte-sonner';

	import { WEBUI_BASE_URL } from '$lib/constants';
	import { WEBUI_NAME, activeOrganizationId, organizations, user } from '$lib/stores';
	import { copyToClipboard } from '$lib/utils';
	import {
		MCP_SESSION_TITLE,
		ORGANIZATION_HEADER,
		claudeCodeCommandFor,
		fetchEndpointUrl,
		organizationHeaderLine,
		selectedOrganization,
		serverName
	} from '$lib/utils/mcpEndpoint';
	import Clipboard from '$lib/components/icons/Clipboard.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';

	const i18n = getContext('i18n');

	let loading = true;
	let endpointUrl: string | null = null;

	$: selected = selectedOrganization($activeOrganizationId, $user?.id, $organizations);
	$: selectedOrganizationId = selected.id;
	$: selectedIsPersonal = selected.isPersonal;
	$: selectedOrganizationName = selected.name ?? $i18n.t('Personal');
	$: headerLine = selectedOrganizationId ? organizationHeaderLine(selectedOrganizationId) : '';

	$: addCommand = endpointUrl
		? claudeCodeCommandFor(selected, serverName($WEBUI_NAME), endpointUrl)
		: '';

	const copy = async (text: string) => {
		if (await copyToClipboard(text)) {
			toast.success($i18n.t('Copied to clipboard'));
		}
	};

	onMount(async () => {
		endpointUrl = await fetchEndpointUrl(WEBUI_BASE_URL);
		loading = false;
	});
</script>

<div class="flex flex-col h-full justify-between space-y-3 text-sm mb-6">
	<div class="space-y-3 overflow-y-scroll max-h-[28rem] lg:max-h-full">
		<div>
			<div class="mb-1 text-sm font-medium">{$i18n.t('MCP Endpoint')}</div>
			<div class="text-xs text-gray-500 dark:text-gray-400">
				{$i18n.t(
					'MCP clients can list and run the skills available to your account through this endpoint.'
				)}
			</div>
		</div>

		<div>
			<div class="mb-1.5 text-xs font-medium">{$i18n.t('Endpoint URL')}</div>
			{#if loading}
				<div class="text-xs text-gray-500">{$i18n.t('Loading...')}</div>
			{:else if endpointUrl}
				<div class="flex w-full min-w-0 items-center gap-2">
					<code
						class="flex-1 w-0 min-w-0 truncate rounded-lg bg-gray-50 dark:bg-gray-850 px-3 py-1.5 text-xs"
						title={endpointUrl}
						data-testid="mcp-endpoint-url">{endpointUrl}</code
					>
					<Tooltip content={$i18n.t('Copy')} className="flex shrink-0">
						<button
							class="shrink-0 p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-850 transition"
							type="button"
							aria-label={$i18n.t('Copy')}
							on:click={() => copy(endpointUrl ?? '')}
						>
							<Clipboard className="size-4" />
						</button>
					</Tooltip>
				</div>
			{:else}
				<div class="text-xs text-gray-500">
					{$i18n.t('This server does not serve an MCP endpoint.')}
				</div>
			{/if}
		</div>

		{#if endpointUrl}
			<hr class="border-gray-100 dark:border-gray-850" />

			<div>
				<div class="mb-1.5 text-xs font-medium">Claude Code</div>
				<div class="text-xs text-gray-500 dark:text-gray-400 mb-1.5">
					{$i18n.t('Add the endpoint, then run /mcp in Claude Code to sign in.')}
				</div>
				<div class="flex w-full min-w-0 items-start gap-2">
					<code
						class="flex-1 w-0 min-w-0 break-words rounded-lg bg-gray-50 dark:bg-gray-850 px-3 py-1.5 text-xs"
						title={addCommand}
						data-testid="mcp-claude-code-command">{addCommand}</code
					>
					<Tooltip content={$i18n.t('Copy')} className="flex shrink-0">
						<button
							class="shrink-0 p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-850 transition"
							type="button"
							aria-label={$i18n.t('Copy')}
							on:click={() => copy(addCommand)}
						>
							<Clipboard className="size-4" />
						</button>
					</Tooltip>
				</div>
			</div>

			<div>
				<div class="mb-1.5 text-xs font-medium">claude.ai</div>
				<div class="text-xs text-gray-500 dark:text-gray-400">
					{$i18n.t('Add a custom connector and enter the endpoint URL.')}
				</div>
			</div>

			<div>
				<div class="mb-1.5 text-xs font-medium">{$i18n.t('Other MCP clients')}</div>
				<div class="text-xs text-gray-500 dark:text-gray-400">
					{$i18n.t('Give the client the endpoint URL. It discovers how to sign in from the URL.')}
				</div>
			</div>

			<div class="text-xs text-gray-500 dark:text-gray-400">
				{$i18n.t(
					'When a client connects, it opens a browser where you sign in and approve its access.'
				)}
			</div>

			<hr class="border-gray-100 dark:border-gray-850" />

			<div>
				<div class="mb-1.5 text-xs font-medium">{$i18n.t('Organization')}</div>
				<div class="text-xs text-gray-500 dark:text-gray-400 mb-1.5">
					{$i18n.t(
						'Calls run in your personal organization unless the client sends the {{header}} header with another organization id.',
						{ header: ORGANIZATION_HEADER }
					)}
				</div>
				{#if selectedOrganizationId}
					<div class="text-xs text-gray-500 dark:text-gray-400 mb-1.5">
						{$i18n.t('Selected organization: {{name}} ({{id}})', {
							name: selectedOrganizationName,
							id: selectedOrganizationId
						})}
						{#if selectedIsPersonal}
							{$i18n.t('(no header needed)')}
						{/if}
					</div>
				{/if}
				{#if selectedOrganizationId && !selectedIsPersonal}
					<div class="flex w-full min-w-0 items-center gap-2">
						<code
							class="flex-1 w-0 min-w-0 truncate rounded-lg bg-gray-50 dark:bg-gray-850 px-3 py-1.5 text-xs"
							title={headerLine}
							data-testid="mcp-organization-header">{headerLine}</code
						>
						<Tooltip content={$i18n.t('Copy')} className="flex shrink-0">
							<button
								class="shrink-0 p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-850 transition"
								type="button"
								aria-label={$i18n.t('Copy')}
								on:click={() => copy(headerLine)}
							>
								<Clipboard className="size-4" />
							</button>
						</Tooltip>
					</div>
				{/if}
			</div>

			<hr class="border-gray-100 dark:border-gray-850" />

			<div>
				<div class="mb-1.5 text-xs font-medium">{$i18n.t('Call history')}</div>
				<div class="text-xs text-gray-500 dark:text-gray-400">
					{$i18n.t(
						'Every call is recorded in a private chat titled "{{title}}" in the organization it ran in. The interface shows that chat read-only.',
						{ title: MCP_SESSION_TITLE }
					)}
				</div>
			</div>
		{/if}
	</div>
</div>
