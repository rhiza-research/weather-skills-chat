"""Web page fetches for web search refuse internal addresses, also after a redirect
or when a host resolves differently at connect time than when it was checked."""

import unittest
from unittest.mock import patch

from aiohttp import web

from open_webui.retrieval.web import utils


class IsPublicIpTest(unittest.TestCase):
    def test_internal_addresses_are_refused(self):
        for ip in [
            "127.0.0.1",
            "10.0.0.1",
            "100.64.0.1",  # carrier-grade NAT
            "169.254.169.254",  # cloud metadata
            "0.0.0.0",
            "::1",
            "fd00::1",
            "fe80::1%eth0",
            "::ffff:127.0.0.1",  # IPv4-mapped
            "64:ff9b::a9fe:a9fe",  # NAT64 of 169.254.169.254
            "2002:a9fe:a9fe::1",  # 6to4 of 169.254.169.254
        ]:
            self.assertFalse(utils.is_public_ip(ip), ip)

    def test_public_addresses_are_allowed(self):
        for ip in ["8.8.8.8", "2606:4700:4700::1111", "64:ff9b::808:808"]:
            self.assertTrue(utils.is_public_ip(ip), ip)

    def test_validate_url_refuses_internal_ip_literals(self):
        for url in [
            "http://127.0.0.1:8080/",
            "http://[::1]:8080/",
            "http://100.64.0.1/",
            "http://169.254.169.254/computeMetadata/v1/",
        ]:
            with self.assertRaises(ValueError, msg=url):
                utils.validate_url(url)


class FetchTest(unittest.IsolatedAsyncioTestCase):
    """A local server stands in for a public site: only 127.0.0.1 counts as public."""

    async def asyncSetUp(self):
        hits = self.hits = []

        async def start(request):
            hits.append("start")
            raise web.HTTPFound(request.query["to"])

        async def page(request):
            hits.append(request.path)
            return web.Response(
                text="<html><body>ok</body></html>", content_type="text/html"
            )

        app = web.Application()
        app.router.add_get("/start", start)
        app.router.add_get("/page", page)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        self.port = site._server.sockets[0].getsockname()[1]

        real = utils.is_public_ip
        self.patches = [
            patch.object(utils, "ENABLE_RAG_LOCAL_WEB_FETCH", False),
            patch.object(
                utils, "is_public_ip", lambda ip: ip == "127.0.0.1" or real(ip)
            ),
        ]
        for p in self.patches:
            p.start()
        self.loader = utils.SafeWebBaseLoader(web_paths=[], continue_on_failure=True)

    async def asyncTearDown(self):
        for p in self.patches:
            p.stop()
        await self.runner.cleanup()

    def url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    async def test_redirect_to_a_public_page_is_followed(self):
        body = await self.loader._fetch(self.url(f"/start?to={self.url('/page')}"))
        self.assertIn("ok", body)
        self.assertEqual(self.hits, ["start", "/page"])

    async def test_redirect_to_an_internal_address_is_refused(self):
        with self.assertRaises(ValueError):
            await self.loader._fetch(
                self.url("/start?to=http://169.254.169.254/computeMetadata/v1/")
            )
        self.assertEqual(self.hits, ["start"])

    async def test_host_resolving_to_internal_address_at_connect_is_refused(self):
        # localhost resolves to a loopback address; reaching _fetch directly skips
        # validate_url, as a host that re-resolves after the check would.
        with self.assertRaises(ValueError):
            await self.loader._fetch(f"http://localhost:{self.port}/page")
        self.assertEqual(self.hits, [])


if __name__ == "__main__":
    unittest.main()
