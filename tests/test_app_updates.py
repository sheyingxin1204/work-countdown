import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app_updates import (
    download_release_asset,
    fetch_latest_release,
    parse_release_payload,
    version_tuple,
)


class _Response:
    def __init__(self, payload):
        self.payload = payload
        self.offset = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, size=-1):
        if self.offset >= len(self.payload):
            return b""
        if size is None or size < 0:
            size = len(self.payload) - self.offset
        chunk = self.payload[self.offset : self.offset + size]
        self.offset += len(chunk)
        return chunk


class AppUpdatesTests(unittest.TestCase):
    def setUp(self):
        self.payload = {
            "tag_name": "v1.3.0",
            "html_url": "https://github.com/example/release",
            "assets": [
                {
                    "name": "BanClock.exe",
                    "browser_download_url": "https://example.test/BanClock.exe",
                    "digest": "",
                }
            ],
        }

    def test_version_tuple_and_release_parsing(self):
        self.assertGreater(version_tuple("v1.10.0"), version_tuple("1.9.9"))
        info, is_newer = parse_release_payload(self.payload, "example/repo", "1.2.0")
        self.assertTrue(is_newer)
        self.assertEqual(info["asset_name"], "BanClock.exe")

    def test_fetch_release_uses_api_request(self):
        calls = []

        def opener(request, timeout):
            calls.append((request.full_url, timeout))
            return _Response(json.dumps(self.payload).encode("utf-8"))

        info, is_newer = fetch_latest_release("example/repo", "1.2.0", "班时钟", opener=opener)
        self.assertTrue(is_newer)
        self.assertEqual(info["url"], "https://github.com/example/release")
        self.assertEqual(calls[0][0], "https://api.github.com/repos/example/repo/releases/latest")

    def test_download_verifies_and_publishes_asset(self):
        content = b"fake executable bytes"
        digest = hashlib.sha256(content).hexdigest()
        release_info = {
            "tag": "v1.3.0",
            "asset_url": "https://example.test/BanClock.exe",
            "digest": f"sha256:{digest}",
        }

        def opener(_request, **_kwargs):
            return _Response(content)

        with TemporaryDirectory() as temp_dir:
            path, actual = download_release_asset(
                release_info,
                Path(temp_dir),
                "班时钟",
                "1.2.0",
                opener=opener,
            )
            self.assertEqual(actual, digest)
            self.assertEqual(path.read_bytes(), content)
            self.assertFalse(list(Path(temp_dir).glob("*.download")))

    def test_download_rejects_bad_digest(self):
        release_info = {
            "tag": "v1.3.0",
            "asset_url": "https://example.test/BanClock.exe",
            "digest": "sha256:bad",
        }
        with TemporaryDirectory() as temp_dir:
            with self.assertRaises(ValueError):
                download_release_asset(
                    release_info,
                    temp_dir,
                    "班时钟",
                    "1.2.0",
                    opener=lambda _request, **_kwargs: _Response(b"fake"),
                )
            self.assertFalse(list(Path(temp_dir).glob("*.download")))


if __name__ == "__main__":
    unittest.main()
