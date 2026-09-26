import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import main


class _Response:
    def __init__(self, body: bytes, content_length: int | None = None):
        self._body = body
        self._used = False
        self.headers = {}
        if content_length is not None:
            self.headers["Content-Length"] = str(content_length)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size=-1):
        if self._used:
            return b""
        self._used = True
        return self._body


class _Opener:
    def __init__(self):
        self.methods = []
        self.urls = []

    def open(self, request, timeout=30):
        url = request.full_url
        self.methods.append(request.get_method())
        self.urls.append(url)

        if "vlscppe.microsoft.com/tags" in url:
            return _Response(b"{}")
        if "getskuinformationbyproductedition" in url:
            body = json.dumps({
                "Skus": [{"Id": "12345", "Language": "Portuguese"}]
            }).encode()
            return _Response(body)
        if "GetProductDownloadLinksBySku" in url:
            body = json.dumps({
                "ProductDownloadLinks": [{
                    "DownloadType": "IsoX64",
                    "Uri": "https://download.test/Win11.iso",
                    "FileName": "Win11.iso",
                }]
            }).encode()
            return _Response(body)
        return _Response(b"x")


class WindowsIsoDownloadRegressionTest(unittest.TestCase):
    def test_microsoft_iso_link_request_uses_get(self):
        opener = _Opener()
        with tempfile.TemporaryDirectory() as tmp:
            iso_path = Path(tmp) / "Windows11.iso"
            chunks = 26
            payload = (b"x" * (4 * 1024 * 1024)) * chunks
            with patch("urllib.request.build_opener", return_value=opener), patch(
                "urllib.request.urlopen", return_value=_Response(b"{}")
            ):
                class _DownloadOpener(_Opener):
                    def open(self, request, timeout=30):
                        if request.full_url == "https://download.test/Win11.iso":
                            self.methods.append(request.get_method())
                            self.urls.append(request.full_url)
                            return _Response(payload, len(payload))
                        return super().open(request, timeout)

                download_opener = _DownloadOpener()
                with patch("urllib.request.build_opener", return_value=download_opener):
                    result = main.ensure_windows_iso(
                        {"AUTO_DOWNLOAD_ISO": "Y", "WINDOWS_ISO_LANGUAGE": "Portuguese"},
                        iso_path,
                    )

            self.assertTrue(result)
            link_calls = [
                method
                for method, url in zip(download_opener.methods, download_opener.urls)
                if "GetProductDownloadLinksBySku" in url
            ]
            self.assertEqual(link_calls, ["GET"])
            self.assertTrue(iso_path.exists())
            self.assertGreater(iso_path.stat().st_size, 100 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
