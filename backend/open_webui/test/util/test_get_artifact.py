"""Fetching an artifact in each of the four representations.

The one-time link is for an agent in a shell that holds no token. The plain link is for a person
signed in to the interface. The two byte-returning forms refuse a file over their size bound
instead of truncating it.
"""

import base64
import unittest
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from open_webui.config import WEBUI_URL
from open_webui.utils.artifacts import (
    MAX_BASE64_SOURCE_BYTES,
    MAX_RETURNABLE_TEXT_BYTES,
    read_artifact_bytes,
)
from open_webui.utils.builtin_tools import (
    ARTIFACT_IMAGE_SUFFIXES,
    ARTIFACT_REPRESENTATIONS,
    DISPLAY_IMAGE_TYPES,
    NOT_TEXT_OR_IMAGE_MESSAGE,
    UNKNOWN_REPRESENTATION_MESSAGE,
    get_artifact,
)

SESSION = "b2c3d4e5-0000-4000-8000-000000000000"
CALLER = {"id": "account-1"}
METADATA = {"chat_id": SESSION}
SERVICE_URL = "https://chat.example"


@contextmanager
def service_url(value=SERVICE_URL):
    """Set the external address, then restore it.

    unittest.mock cannot patch this: it reads the target's __dict__, and PersistentConfig raises
    TypeError for __dict__.
    """
    previous = WEBUI_URL.value
    WEBUI_URL.value = value
    try:
        yield
    finally:
        WEBUI_URL.value = previous


class BoundsAreTheMeasuredOnesTest(unittest.TestCase):
    def test_text_is_bounded_at_one_hundred_and_twenty_eight_kibibytes(self):
        # Same bound as the sibling service. At about four bytes per token this is roughly 32,000
        # tokens.
        self.assertEqual(MAX_RETURNABLE_TEXT_BYTES, 131_072)

    def test_the_base64_source_bound_encodes_to_the_text_bound(self):
        encoded = len(base64.b64encode(b"x" * MAX_BASE64_SOURCE_BYTES))
        self.assertLessEqual(encoded, MAX_RETURNABLE_TEXT_BYTES)


class ReadArtifactBytesTest(unittest.TestCase):
    def test_a_file_inside_the_bound_is_returned_whole(self):
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "small.txt"
            target.write_bytes(b"hello")
            with patch(
                "open_webui.utils.artifacts.resolve_in_sandbox", return_value=target
            ):
                self.assertEqual(read_artifact_bytes(SESSION, "small.txt", 10), b"hello")

    def test_a_file_past_the_bound_is_refused_not_shortened(self):
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "big.txt"
            target.write_bytes(b"x" * 100)
            with patch(
                "open_webui.utils.artifacts.resolve_in_sandbox", return_value=target
            ):
                with self.assertRaises(ValueError) as raised:
                    read_artifact_bytes(SESSION, "big.txt", 10)
        self.assertIn("100", str(raised.exception))
        self.assertIn("10", str(raised.exception))

    def test_a_missing_file_is_reported_as_missing(self):
        with TemporaryDirectory() as tmp:
            with patch(
                "open_webui.utils.artifacts.resolve_in_sandbox",
                return_value=Path(tmp) / "absent.txt",
            ):
                with self.assertRaises(FileNotFoundError):
                    read_artifact_bytes(SESSION, "absent.txt", 10)


class RepresentationTest(unittest.IsolatedAsyncioTestCase):
    async def fetch(self, path, representation="content", data=b"rain", suffix=".txt"):
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / f"artifact{suffix}"
            target.write_bytes(data)
            with patch(
                "open_webui.utils.artifacts.resolve_in_sandbox", return_value=target
            ), service_url():
                return await get_artifact(
                    path, representation, __user__=CALLER, __metadata__=METADATA
                )

    async def test_there_are_exactly_four(self):
        self.assertEqual(len(ARTIFACT_REPRESENTATIONS), 4)

    async def test_text_comes_back_as_its_own_text(self):
        self.assertEqual(await self.fetch("a.txt", "content"), "rain")

    async def test_base64_comes_back_encoded(self):
        out = await self.fetch("a.txt", "base64")
        self.assertEqual(base64.b64decode(out), b"rain")

    async def test_an_image_comes_back_as_a_data_url(self):
        out = await self.fetch("a.png", "content", data=b"\x89PNG", suffix=".png")
        self.assertTrue(out.startswith("data:image/png;base64,"))

    async def test_something_that_is_neither_says_what_to_ask_for_instead(self):
        out = await self.fetch("a.bin", "content", data=b"\xff\xfe\x00", suffix=".bin")
        self.assertEqual(out, NOT_TEXT_OR_IMAGE_MESSAGE)

    async def test_a_fifth_representation_is_refused(self):
        self.assertEqual(
            await self.fetch("a.txt", "carrier-pigeon"), UNKNOWN_REPRESENTATION_MESSAGE
        )

    async def test_no_path_is_refused(self):
        out = await self.fetch("", "content")
        self.assertIn("relative path", out)


class LinkTest(unittest.IsolatedAsyncioTestCase):
    async def link(self, path):
        with service_url():
            return await get_artifact(
                path, "link", __user__=CALLER, __metadata__=METADATA
            )

    async def test_it_is_the_route_that_already_serves_artifact_content(self):
        # The existing route checks the interface session, so a signed-in person can open it.
        out = await self.link("plots/rain.png")
        self.assertEqual(
            out,
            f"{SERVICE_URL}/api/v1/chats/{SESSION}/artifacts/content?path=plots/rain.png",
        )

    async def test_a_path_needing_escaping_is_escaped(self):
        out = await self.link("plots/a b.png")
        self.assertIn("a%20b.png", out)


class OnceTest(unittest.IsolatedAsyncioTestCase):
    async def once(self, available=True, nonce="tok"):
        with service_url(), patch(
            "open_webui.utils.artifact_handoff.handoff_available", return_value=available
        ), patch("open_webui.utils.artifact_handoff.mint", return_value=nonce):
            return await get_artifact(
                "rain.zarr.zip", "once", __user__=CALLER, __metadata__=METADATA
            )

    async def test_it_returns_a_credential_free_url(self):
        out = await self.once()
        self.assertEqual(out, f"{SERVICE_URL}/api/v1/artifact-handoff/tok")

    async def test_without_a_store_it_says_so_and_names_the_alternatives(self):
        # An in-process store is not single use across multiple workers, so there is no fallback.
        out = await self.once(available=False)
        self.assertIn("content", out)
        self.assertIn("base64", out)


class NoSessionTest(unittest.IsolatedAsyncioTestCase):
    async def test_a_fetch_without_a_session_is_refused(self):
        out = await get_artifact("a.txt", "content", __user__=CALLER, __metadata__={})
        self.assertIn("without a session", out)

    async def test_the_temporary_chat_sentinel_is_refused(self):
        out = await get_artifact(
            "a.txt", "content", __user__=CALLER, __metadata__={"chat_id": "local"}
        )
        self.assertIn("without a session", out)


class ImageContentTest(unittest.IsolatedAsyncioTestCase):
    """An image comes back as a data URL, within the same bound as other returnable content.

    An image over MAX_BASE64_SOURCE_BYTES is refused with a message naming its size and the limit.
    Allowing images up to the display bound would let the endpoint's result bound cut the data URL
    mid-base64.
    """

    @contextmanager
    def artifact(self, name, data):
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / name
            target.write_bytes(data)
            with patch(
                "open_webui.utils.artifacts.resolve_in_sandbox", return_value=target
            ), service_url():
                yield

    async def fetch(self, name):
        return await get_artifact(
            name, "content", __user__=CALLER, __metadata__=METADATA
        )

    async def test_an_image_inside_the_bound_comes_back_as_a_data_url(self):
        with self.artifact("small.png", b"\x89PNG\r\n\x1a\n" + b"x" * 32):
            out = await self.fetch("small.png")
        self.assertTrue(out.startswith("data:image/png;base64,"))

    async def test_an_oversized_image_is_refused_rather_than_shortened(self):
        with self.artifact("big.png", b"x" * (MAX_BASE64_SOURCE_BYTES + 1)):
            out = await self.fetch("big.png")
        self.assertNotIn("base64,", out)
        self.assertIn(str(MAX_BASE64_SOURCE_BYTES), out)

    async def test_the_refusal_names_the_size_that_was_refused(self):
        oversized = MAX_BASE64_SOURCE_BYTES + 17
        with self.artifact("big.png", b"x" * oversized):
            out = await self.fetch("big.png")
        self.assertIn(str(oversized), out)

    async def test_what_comes_back_stays_inside_the_returnable_bound(self):
        with self.artifact("edge.png", b"x" * MAX_BASE64_SOURCE_BYTES):
            out = await self.fetch("edge.png")
        self.assertLessEqual(len(out.encode("utf-8")), MAX_RETURNABLE_TEXT_BYTES + 64)

    async def test_a_jpg_is_typed_as_jpeg(self):
        # image/jpg is not a registered media type. The type comes from DISPLAY_IMAGE_TYPES.
        with self.artifact("photo.jpg", b"\xff\xd8\xff" + b"x" * 16):
            out = await self.fetch("photo.jpg")
        self.assertTrue(out.startswith("data:image/jpeg;base64,"))

    async def test_every_accepted_suffix_has_a_registered_type(self):
        for suffix in ARTIFACT_IMAGE_SUFFIXES:
            self.assertIn(suffix, DISPLAY_IMAGE_TYPES, suffix)


if __name__ == "__main__":
    unittest.main()
