"""The MCP endpoint's OAuth 2.1 authorization server.

It is outside the endpoint's package because its consent page reads the web interface's session
cookie with the interface's auth module, and test_mcp_credential_isolation forbids the endpoint's
modules from importing that module directly. The rule covers direct imports only: the endpoint's
package imports the consent routes from here, and they import the interface's auth module.
"""
