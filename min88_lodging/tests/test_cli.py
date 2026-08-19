import tempfile
import unittest
from unittest import mock

from min88_lodging.cli import build_parser, main


class CliTests(unittest.TestCase):
    def test_defaults_and_parse_dispatch(self):
        args = build_parser().parse_args(["parse"])
        self.assertTrue(args.data_dir.endswith("source/min88-lodging"))
        self.assertTrue(args.output.endswith("output/min88-lodging/raw.jsonl"))
        with mock.patch("min88_lodging.cli.parse_archive",
                        return_value={"records": 3, "skipped": 0, "errors": []}) as function:
            self.assertEqual(main(["parse", "--data-dir", "/archive", "--output", "/tmp/raw.jsonl"]), 0)
        function.assert_called_once_with("/archive", "/tmp/raw.jsonl")

    def test_crawl_and_verify_failures_return_nonzero(self):
        with mock.patch("min88_lodging.cli.crawl_detail_archive",
                        return_value={"fetched": 1, "skipped": 0, "failed": 1}):
            self.assertEqual(main(["crawl-details", "--data-dir", "/archive", "--delay", "0"]), 1)
        result = {"ok": False, "errors": ["bad hash"], "warnings": [], "index_records": 1,
                  "detail_parseable": 1, "raw_records": 1, "v1_records": 1}
        with mock.patch("min88_lodging.cli.verify", return_value=result):
            self.assertEqual(main(["verify", "--data-dir", "/archive", "--output-dir", "/output"]), 1)

    def test_geocode_uses_archive_cache_default(self):
        stats = {"records": 1, "geocoded": 1, "no_request": 0, "not_found": 0, "errors": 0}
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch("min88_lodging.cli.enrich_file", return_value=stats) as function:
                code = main(["geocode", "--data-dir", directory, "input.jsonl", "--output", "out.jsonl",
                             "--delay", "0"])
            self.assertEqual(code, 0)
            self.assertEqual(function.call_args.args[2], directory + "/google-maps")

    def test_geocode_fetch_errors_return_nonzero(self):
        stats = {"records": 1, "geocoded": 0, "no_request": 0, "not_found": 0,
                 "fetch_errors": 1}
        with mock.patch("min88_lodging.cli.enrich_file", return_value=stats):
            self.assertEqual(main(["geocode", "input.jsonl", "--output", "out.jsonl"]), 1)


if __name__ == "__main__":
    unittest.main()
