import json
import os
import tempfile
import unittest
from unittest import mock

from min88_lodging.crawler import HttpClient, crawl_details, crawl_index
from min88_lodging.crawler.storage import atomic_write_bytes

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "index-list.html")


def detail(source_id, title="Lodging"):
    return f'<html><head><link rel="canonical" href="https://min88.jp/inn/{source_id}/"></head><body><h1 id="post_title">{title}</h1></body></html>'.encode()


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get_bytes(self, url):
        self.calls.append(url)
        return self.responses.pop(0)


class CrawlerTests(unittest.TestCase):
    def test_index_resume_and_force(self):
        with open(FIXTURE, "rb") as source:
            body = source.read()
        with tempfile.TemporaryDirectory() as data_dir:
            first = FakeClient([(200, {"ETag": "v1"}, body)])
            result = crawl_index(data_dir, client=first)
            self.assertEqual(result["record_count"], 6)
            self.assertEqual(result["archive"]["status"], "fetched")
            never = FakeClient([])
            self.assertEqual(crawl_index(data_dir, client=never)["archive"]["status"], "skipped")
            self.assertEqual(never.calls, [])
            forced = FakeClient([(200, {}, body)])
            self.assertEqual(crawl_index(data_dir, force=True, client=forced)["archive"]["status"], "fetched")
            with open(os.path.join(data_dir, "index.json"), encoding="utf-8") as source:
                self.assertNotIn("retrieved_at", json.load(source))

    def test_details_resume_failure_continue_and_canonical_rejection(self):
        with tempfile.TemporaryDirectory() as data_dir:
            records = [
                {"source_id": "1", "source_url": "https://min88.jp/inn/1/"},
                {"source_id": "2", "source_url": "https://min88.jp/inn/2/"},
                {"source_id": "3", "source_url": "https://min88.jp/inn/3/"},
            ]
            os.makedirs(os.path.join(data_dir, "records", "1"))
            with open(os.path.join(data_dir, "records", "1", "page.html"), "wb") as output:
                output.write(detail("1"))
            with open(os.path.join(data_dir, "index.json"), "w", encoding="utf-8") as output:
                json.dump({"records": records}, output)
            client = FakeClient([(404, {}, b"missing"), (200, {}, detail("999"))])
            result = crawl_details(data_dir, client=client)
            self.assertEqual((result["skipped"], result["failed"]), (1, 2))
            self.assertIn("canonical", result["records"][2]["error"])
            self.assertFalse(os.path.exists(os.path.join(data_dir, "records", "3", "page.html")))

    def test_http_retries_retryable_status_only(self):
        responses = iter([(429, {}, b""), (503, {}, b""), (200, {}, b"ok")])
        calls = []
        sleeps = []
        client = HttpClient(delay=0, request=lambda url, timeout: calls.append(url) or next(responses), sleep=sleeps.append)
        self.assertEqual(client.get_bytes("https://min88.jp/test")[0], 200)
        self.assertEqual(len(calls), 3)
        self.assertEqual(sleeps, [1, 2])

    def test_failed_force_does_not_replace_valid_archive(self):
        with tempfile.TemporaryDirectory() as data_dir:
            records = [{"source_id": "1", "source_url": "https://min88.jp/inn/1/"}]
            page = os.path.join(data_dir, "records", "1", "page.html")
            os.makedirs(os.path.dirname(page))
            original = detail("1", "original")
            with open(page, "wb") as output:
                output.write(original)
            with open(os.path.join(data_dir, "index.json"), "w", encoding="utf-8") as output:
                json.dump({"records": records}, output)
            result = crawl_details(data_dir, force=True, client=FakeClient([(200, {}, detail("2"))]))
            self.assertEqual(result["failed"], 1)
            with open(page, "rb") as source:
                self.assertEqual(source.read(), original)

    def test_malformed_index_records_fail_without_network_or_path_access(self):
        with tempfile.TemporaryDirectory() as data_dir:
            records = [
                {"source_id": "../escape", "source_url": "https://min88.jp/inn/../escape/"},
                {"source_id": "2", "source_url": "https://evil.test/inn/2/"},
                {"source_id": 3, "source_url": "https://min88.jp/inn/3/"},
                {"source_id": "4", "source_url": "https://min88.jp/inn/4"},
            ]
            with open(os.path.join(data_dir, "index.json"), "w", encoding="utf-8") as output:
                json.dump({"records": records}, output)
            client = FakeClient([])
            result = crawl_details(data_dir, client=client)
            self.assertEqual(result["failed"], 4)
            self.assertEqual(client.calls, [])
            self.assertFalse(os.path.exists(os.path.join(data_dir, "escape")))

    def test_interrupted_atomic_write_preserves_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "page.html")
            with open(path, "wb") as output:
                output.write(b"original")
            with mock.patch("min88_lodging.crawler.storage.os.replace", side_effect=OSError("interrupted")):
                with self.assertRaises(OSError):
                    atomic_write_bytes(path, b"replacement")
            with open(path, "rb") as source:
                self.assertEqual(source.read(), b"original")
            self.assertEqual(os.listdir(directory), ["page.html"])


if __name__ == "__main__":
    unittest.main()
