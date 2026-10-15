import unittest
from types import SimpleNamespace
from unittest.mock import patch

from open_webui.retrieval.web.utils import SafeWebBaseLoader
from open_webui.test.util.test_document_loaders import no_network

URL = "https://weather.example/forecast"
HTML = (
    "<html lang='en'><head><title>Nairobi Forecast</title>"
    "<meta name='description' content='Daily outlook'></head>"
    "<body><p>Showers expected after noon.</p></body></html>"
)
EXPECTED_METADATA = {
    "source": URL,
    "title": "Nairobi Forecast",
    "description": "Daily outlook",
    "language": "en",
}


class FakeResponse:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def raise_for_status(self):
        return None

    async def text(self):
        return HTML


class FakeClientSession:
    """Stands in for aiohttp.ClientSession; records each GET."""

    gets: list = []

    def __init__(self, *args, **kwargs):
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def get(self, url, **kwargs):
        FakeClientSession.gets.append((url, kwargs))
        return FakeResponse()


class SafeWebBaseLoaderTest(unittest.IsolatedAsyncioTestCase):
    def test_load_parses_fetched_page(self):
        loader = SafeWebBaseLoader(web_paths=[URL])
        response = SimpleNamespace(
            text=HTML, apparent_encoding="utf-8", encoding=None, raise_for_status=lambda: None
        )
        with patch.object(loader.session, "get", return_value=response) as get, no_network() as calls:
            docs = loader.load()
        self.assertEqual(calls, [])
        get.assert_called_once_with(URL)
        self.assertEqual(len(docs), 1)
        self.assertIn("Showers expected after noon.", docs[0].page_content)
        self.assertEqual(docs[0].metadata, EXPECTED_METADATA)

    async def test_aload_parses_fetched_page(self):
        FakeClientSession.gets = []
        loader = SafeWebBaseLoader(web_paths=[URL])
        with (
            patch("open_webui.retrieval.web.utils.aiohttp.ClientSession", FakeClientSession),
            no_network() as calls,
        ):
            docs = await loader.aload()
        self.assertEqual(calls, [])
        self.assertEqual([url for url, _ in FakeClientSession.gets], [URL])
        self.assertIn("headers", FakeClientSession.gets[0][1])
        self.assertEqual(len(docs), 1)
        self.assertIn("Showers expected after noon.", docs[0].page_content)
        self.assertEqual(docs[0].metadata, EXPECTED_METADATA)


if __name__ == "__main__":
    unittest.main()
