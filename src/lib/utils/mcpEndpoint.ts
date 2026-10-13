/** Path of the protected resource metadata document for the MCP endpoint (RFC 9728). */
export const PROTECTED_RESOURCE_METADATA_PATH = '/.well-known/oauth-protected-resource/mcp';

/** Title of the private chat that records an account's MCP calls in an organization. */
export const MCP_SESSION_TITLE = 'MCP session';

/** Header that names the organization an MCP call runs in. */
export const ORGANIZATION_HEADER = 'X-Organization-Id';

/**
 * The endpoint URL from a protected resource metadata document: its `resource` with a trailing
 * slash, or null when the document has no string `resource`.
 */
export function endpointUrlFromMetadata(metadata: unknown): string | null {
	if (!metadata || typeof metadata !== 'object') {
		return null;
	}
	const resource = (metadata as { resource?: unknown }).resource;
	if (typeof resource !== 'string' || resource.trim() === '') {
		return null;
	}
	return resource.endsWith('/') ? resource : `${resource}/`;
}

/**
 * Fetch the protected resource metadata document from `baseUrl` and return the endpoint URL,
 * or null when the document is not served or has no `resource`.
 */
export async function fetchEndpointUrl(
	baseUrl: string,
	fetchImpl: typeof fetch = fetch
): Promise<string | null> {
	try {
		const response = await fetchImpl(`${baseUrl}${PROTECTED_RESOURCE_METADATA_PATH}`);
		if (!response.ok) {
			return null;
		}
		return endpointUrlFromMetadata(await response.json());
	} catch {
		return null;
	}
}

/** A Claude Code server name from the interface name: lowercase, runs of other characters as "-". */
export function serverName(interfaceName: string | null | undefined): string {
	const name = (interfaceName ?? '')
		.toLowerCase()
		.replace(/[^a-z0-9]+/g, '-')
		.replace(/^-+|-+$/g, '');
	return name || 'mcp';
}

/** The header line a client sends to run calls in the organization with id `organizationId`. */
export function organizationHeaderLine(organizationId: string): string {
	return `${ORGANIZATION_HEADER}: ${organizationId}`;
}

/**
 * The Claude Code command that adds the endpoint as an HTTP MCP server. With an
 * `organizationId`, the command also sends the organization header.
 */
export function claudeCodeAddCommand(
	name: string,
	url: string,
	organizationId: string | null = null
): string {
	const command = `claude mcp add --transport http ${name} ${url}`;
	return organizationId
		? `${command} --header "${organizationHeaderLine(organizationId)}"`
		: command;
}

export interface OrganizationSummary {
	id: string;
	name?: string;
	kind?: string;
}

export interface SelectedOrganization {
	id: string;
	isPersonal: boolean;
	/** The organization's name, or null for the personal organization. */
	name: string | null;
}

/**
 * The organization selected in the interface. Without an active organization it is the personal
 * organization, whose id is the user id. As on the endpoint, an organization is personal only when
 * its id is the user id. A shared organization missing from the list is named by its id.
 */
export function selectedOrganization(
	activeOrganizationId: string | null | undefined,
	userId: string | null | undefined,
	organizations: OrganizationSummary[] | null | undefined
): SelectedOrganization {
	const id = activeOrganizationId || userId || '';
	const organization = (organizations ?? []).find((org) => org.id === id);
	const isPersonal = id === (userId ?? '');
	return { id, isPersonal, name: isPersonal ? null : (organization?.name ?? id) };
}

/**
 * The Claude Code command for the selected organization: with the organization header for a
 * shared organization, without it for the personal one.
 */
export function claudeCodeCommandFor(
	selected: SelectedOrganization,
	name: string,
	url: string
): string {
	return claudeCodeAddCommand(name, url, selected.isPersonal ? null : selected.id);
}
