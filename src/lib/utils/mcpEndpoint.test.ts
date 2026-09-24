import { expect, test } from 'vitest';
import {
	claudeCodeAddCommand,
	claudeCodeCommandFor,
	MCP_SESSION_TITLE,
	endpointUrlFromMetadata,
	fetchEndpointUrl,
	organizationHeaderLine,
	PROTECTED_RESOURCE_METADATA_PATH,
	selectedOrganization,
	serverName
} from './mcpEndpoint';

test('the endpoint URL is the resource with a trailing slash', () => {
	expect(endpointUrlFromMetadata({ resource: 'https://chat.test/mcp' })).toBe(
		'https://chat.test/mcp/'
	);
});

test('a resource that already ends in a slash is kept', () => {
	expect(endpointUrlFromMetadata({ resource: 'https://chat.test/mcp/' })).toBe(
		'https://chat.test/mcp/'
	);
});

test('a document without a string resource gives no URL', () => {
	expect(endpointUrlFromMetadata(null)).toBeNull();
	expect(endpointUrlFromMetadata('https://chat.test/mcp')).toBeNull();
	expect(endpointUrlFromMetadata({})).toBeNull();
	expect(endpointUrlFromMetadata({ resource: 7 })).toBeNull();
	expect(endpointUrlFromMetadata({ resource: '  ' })).toBeNull();
});

test('the URL is read from the document at the base URL, not built from it', async () => {
	const requested: string[] = [];
	const fetchImpl = (async (input: RequestInfo | URL) => {
		requested.push(String(input));
		return new Response(JSON.stringify({ resource: 'https://public.test/mcp' }), {
			status: 200
		});
	}) as typeof fetch;

	expect(await fetchEndpointUrl('http://localhost:8080', fetchImpl)).toBe(
		'https://public.test/mcp/'
	);
	expect(requested).toEqual([`http://localhost:8080${PROTECTED_RESOURCE_METADATA_PATH}`]);
});

test('a document that is not served gives no URL', async () => {
	const notFound = (async () => new Response('', { status: 404 })) as typeof fetch;
	expect(await fetchEndpointUrl('', notFound)).toBeNull();
});

test('a failed request or a body that is not JSON gives no URL', async () => {
	const failing = (async () => {
		throw new TypeError('network');
	}) as typeof fetch;
	const notJson = (async () => new Response('<html>', { status: 200 })) as typeof fetch;
	expect(await fetchEndpointUrl('', failing)).toBeNull();
	expect(await fetchEndpointUrl('', notJson)).toBeNull();
});

test('the server name is the interface name in lowercase with dashes', () => {
	expect(serverName('Rhiza Weather Chat')).toBe('rhiza-weather-chat');
	expect(serverName('  --Open WebUI (dev)-- ')).toBe('open-webui-dev');
	expect(serverName('')).toBe('mcp');
	expect(serverName(undefined)).toBe('mcp');
});

test('the Claude Code command adds an HTTP server with the name and URL', () => {
	expect(claudeCodeAddCommand('rhiza', 'https://chat.test/mcp/')).toBe(
		'claude mcp add --transport http rhiza https://chat.test/mcp/'
	);
	expect(claudeCodeAddCommand('rhiza', 'https://chat.test/mcp/', null)).toBe(
		'claude mcp add --transport http rhiza https://chat.test/mcp/'
	);
});

test('the Claude Code command for a shared organization sends its header', () => {
	expect(claudeCodeAddCommand('rhiza', 'https://chat.test/mcp/', 'org-1')).toBe(
		'claude mcp add --transport http rhiza https://chat.test/mcp/ --header "X-Organization-Id: org-1"'
	);
});

test('the organization header line names the organization id', () => {
	expect(organizationHeaderLine('org-1')).toBe('X-Organization-Id: org-1');
});

const ORGANIZATIONS = [
	{ id: 'user-1', name: 'Personal', kind: 'personal' },
	{ id: 'org-1', name: 'Field team', kind: 'team' }
];

test('the personal organization is selected when the active id is the user id', () => {
	expect(selectedOrganization('user-1', 'user-1', ORGANIZATIONS)).toEqual({
		id: 'user-1',
		isPersonal: true,
		name: null
	});
});

test('without an active organization the personal organization is selected', () => {
	expect(selectedOrganization(null, 'user-1', ORGANIZATIONS)).toEqual({
		id: 'user-1',
		isPersonal: true,
		name: null
	});
	expect(selectedOrganization(undefined, 'user-1', undefined)).toEqual({
		id: 'user-1',
		isPersonal: true,
		name: null
	});
});

test('a shared organization is selected with its name', () => {
	expect(selectedOrganization('org-1', 'user-1', ORGANIZATIONS)).toEqual({
		id: 'org-1',
		isPersonal: false,
		name: 'Field team'
	});
});

test('a shared organization missing from the list is named by its id', () => {
	expect(selectedOrganization('org-2', 'user-1', ORGANIZATIONS)).toEqual({
		id: 'org-2',
		isPersonal: false,
		name: 'org-2'
	});
});

test('an organization is personal only when its id is the user id', () => {
	expect(
		selectedOrganization('personal-2', 'user-1', [
			{ id: 'personal-2', name: 'Other', kind: 'personal' }
		])
	).toEqual({ id: 'personal-2', isPersonal: false, name: 'Other' });
});

test('the Claude Code command built from the selected shared organization sends its header', () => {
	const selected = selectedOrganization('org-1', 'user-1', ORGANIZATIONS);
	expect(claudeCodeCommandFor(selected, 'rhiza', 'https://chat.test/mcp/')).toBe(
		'claude mcp add --transport http rhiza https://chat.test/mcp/ --header "X-Organization-Id: org-1"'
	);
});

test('the Claude Code command built from the selected personal organization sends no header', () => {
	const selected = selectedOrganization('user-1', 'user-1', ORGANIZATIONS);
	expect(claudeCodeCommandFor(selected, 'rhiza', 'https://chat.test/mcp/')).toBe(
		'claude mcp add --transport http rhiza https://chat.test/mcp/'
	);
});

test('the session chat title is MCP session', () => {
	expect(MCP_SESSION_TITLE).toBe('MCP session');
});
