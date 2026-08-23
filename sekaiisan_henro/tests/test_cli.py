import os
import tempfile
import unittest

from sekaiisan_henro.__main__ import build_parser, dispatch
from sekaiisan_henro.tests import helpers

SNAPSHOT_SHA = "cd" * 32


class TestCliDispatch(unittest.TestCase):
    def test_no_command_defaults_to_fetch(self):
        parser = build_parser()
        args = parser.parse_args(["--data-dir", "/tmp/x", "--timeout", "5"])
        self.assertIsNone(args.command)
        self.assertEqual(args.data_dir, "/tmp/x")
        self.assertEqual(args.timeout, 5)

    def test_no_command_uses_defaults(self):
        parser = build_parser()
        args = parser.parse_args([])
        self.assertIsNone(args.command)
        self.assertEqual(args.data_dir, "source/88sekaiisan-henro")
        self.assertEqual(args.timeout, 30)

    def test_fetch_explicit_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["fetch"])
        self.assertEqual(args.command, "fetch")

    def test_normalize_subcommand_defaults(self):
        parser = build_parser()
        args = parser.parse_args(["normalize"])
        self.assertEqual(args.command, "normalize")
        self.assertEqual(args.snapshot, "current")
        self.assertEqual(args.data_dir, "source/88sekaiisan-henro")
        self.assertEqual(args.output, "output/sekaiisan-henro-normalized.json")

    def test_topology_inventory_subcommand_defaults(self):
        parser = build_parser()
        args = parser.parse_args(["topology-inventory"])
        self.assertEqual(args.command, "topology-inventory")
        self.assertEqual(args.input, "output/sekaiisan-henro-normalized.json")
        self.assertEqual(args.output, "output/sekaiisan-henro-topology-inventory.json")

    def test_dispatch_topology_inventory_writes_atomically(self):
        data_dir = tempfile.mkdtemp()
        helpers.write_snapshot(data_dir, SNAPSHOT_SHA, helpers.standard_route_counts(), list(range(1, 89)))
        normalized = os.path.join(data_dir, "normalized.json")
        parser = build_parser()
        args = parser.parse_args(["normalize", "--snapshot", "current", "--data-dir", data_dir, "--output", normalized])
        dispatch(args)
        inventory = os.path.join(data_dir, "inventory.json")
        args = parser.parse_args(["topology-inventory", "--input", normalized, "--output", inventory])
        result = dispatch(args)
        self.assertEqual(result["kind"], "topology_inventory")
        self.assertTrue(os.path.exists(inventory))
        self.assertFalse(os.path.exists(inventory + ".tmp"))

    def test_dispatch_normalize_uses_local_files_not_network(self):
        data_dir = tempfile.mkdtemp()
        helpers.write_snapshot(data_dir, SNAPSHOT_SHA, helpers.standard_route_counts(), list(range(1, 89)))
        output = os.path.join(data_dir, "out.json")
        parser = build_parser()
        args = parser.parse_args(["normalize", "--snapshot", "current", "--data-dir", data_dir, "--output", output])
        result = dispatch(args)
        self.assertEqual(result["snapshot_sha256"], SNAPSHOT_SHA)
        self.assertEqual(result["accounting"]["temples"], 88)
        self.assertTrue(os.path.exists(output))


if __name__ == "__main__":
    unittest.main()