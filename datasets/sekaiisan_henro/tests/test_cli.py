import json
import os
import tempfile
import unittest

from datasets.sekaiisan_henro.__main__ import build_parser, dispatch
from datasets.sekaiisan_henro.tests import helpers

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
        self.assertEqual(args.data_dir, "datasets/sekaiisan_henro/raw")
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
        self.assertEqual(args.data_dir, "datasets/sekaiisan_henro/raw")
        self.assertEqual(args.output, "datasets/sekaiisan_henro/output/sekaiisan-henro-normalized.json")

    def test_topology_inventory_subcommand_defaults(self):
        parser = build_parser()
        args = parser.parse_args(["topology-inventory"])
        self.assertEqual(args.command, "topology-inventory")
        self.assertEqual(args.input, "datasets/sekaiisan_henro/output/sekaiisan-henro-normalized.json")
        self.assertEqual(args.output, "datasets/sekaiisan_henro/output/sekaiisan-henro-topology-inventory.json")

    def test_build_graph_subcommand_defaults(self):
        parser = build_parser()
        args = parser.parse_args(["build-graph"])
        self.assertEqual(args.command, "build-graph")
        self.assertEqual(args.input, "datasets/sekaiisan_henro/output/sekaiisan-henro-normalized.json")
        self.assertEqual(args.inventory, "datasets/sekaiisan_henro/output/sekaiisan-henro-topology-inventory.json")
        self.assertEqual(args.output, "datasets/sekaiisan_henro/output/sekaiisan-henro-graph.json")

    def test_apply_proximity_subcommand_defaults(self):
        parser = build_parser()
        args = parser.parse_args(["apply-proximity"])
        self.assertEqual(args.command, "apply-proximity")
        self.assertEqual(args.graph, "datasets/sekaiisan_henro/output/sekaiisan-henro-graph.json")
        self.assertEqual(args.inventory, "datasets/sekaiisan_henro/output/sekaiisan-henro-topology-inventory.json")
        self.assertEqual(args.input, "datasets/sekaiisan_henro/output/sekaiisan-henro-normalized.json")
        self.assertEqual(args.output, "datasets/sekaiisan_henro/output/sekaiisan-henro-graph-proximity.json")

    def test_build_anchors_subcommand_defaults(self):
        parser = build_parser()
        args = parser.parse_args(["build-anchors"])
        self.assertEqual(args.command, "build-anchors")
        self.assertEqual(args.graph, "datasets/sekaiisan_henro/output/sekaiisan-henro-graph-proximity.json")
        self.assertEqual(args.input, "datasets/sekaiisan_henro/output/sekaiisan-henro-normalized.json")
        self.assertEqual(args.output, "datasets/sekaiisan_henro/output/sekaiisan-henro-graph-anchors.json")

    def test_build_sections_subcommand_defaults(self):
        parser = build_parser()
        args = parser.parse_args(["build-sections"])
        self.assertEqual(args.command, "build-sections")
        self.assertEqual(args.input, "datasets/sekaiisan_henro/output/sekaiisan-henro-graph-anchors.json")
        self.assertEqual(args.output, "datasets/sekaiisan_henro/output/sekaiisan-henro-temple-sections.json")

    def test_build_section_corridors_subcommand_defaults(self):
        parser = build_parser()
        args = parser.parse_args(["build-section-corridors"])
        self.assertEqual(args.command, "build-section-corridors")
        self.assertEqual(args.input, "datasets/sekaiisan_henro/output/sekaiisan-henro-graph-anchors.json")
        self.assertEqual(args.output, "datasets/sekaiisan_henro/output/sekaiisan-henro-section-corridors.json")
        self.assertEqual(args.geojson, "datasets/sekaiisan_henro/output/sekaiisan-henro-section-corridor-edges.geojson")

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

    def test_dispatch_build_graph_writes_atomically(self):
        data_dir = tempfile.mkdtemp()
        helpers.write_snapshot(data_dir, SNAPSHOT_SHA, helpers.standard_route_counts(), list(range(1, 89)))
        parser = build_parser()
        normalized = os.path.join(data_dir, "normalized.json")
        inventory = os.path.join(data_dir, "inventory.json")
        graph_out = os.path.join(data_dir, "graph.json")
        dispatch(parser.parse_args(["normalize", "--snapshot", "current",
                                    "--data-dir", data_dir, "--output", normalized]))
        dispatch(parser.parse_args(["topology-inventory", "--input", normalized,
                                    "--output", inventory]))
        result = dispatch(parser.parse_args(["build-graph", "--input", normalized,
                                             "--inventory", inventory, "--output", graph_out]))
        self.assertEqual(result["kind"], "exact_route_graph")
        self.assertTrue(os.path.exists(graph_out))
        self.assertFalse(os.path.exists(graph_out + ".tmp"))
        self.assertEqual(result["accounting"]["proximity_connections_applied"], 0)
        self.assertEqual(result["accounting"]["ambiguous_crossings_connected"], 0)

    def test_dispatch_apply_proximity_writes_atomically(self):
        data_dir = tempfile.mkdtemp()
        helpers.write_snapshot(data_dir, SNAPSHOT_SHA, helpers.standard_route_counts(), list(range(1, 89)))
        parser = build_parser()
        normalized = os.path.join(data_dir, "normalized.json")
        inventory = os.path.join(data_dir, "inventory.json")
        graph_out = os.path.join(data_dir, "graph.json")
        prox_out = os.path.join(data_dir, "graph-proximity.json")
        dispatch(parser.parse_args(["normalize", "--snapshot", "current",
                                    "--data-dir", data_dir, "--output", normalized]))
        dispatch(parser.parse_args(["topology-inventory", "--input", normalized,
                                    "--output", inventory]))
        dispatch(parser.parse_args(["build-graph", "--input", normalized,
                                    "--inventory", inventory, "--output", graph_out]))
        result = dispatch(parser.parse_args(["apply-proximity", "--graph", graph_out,
                                             "--inventory", inventory, "--input", normalized,
                                             "--output", prox_out]))
        self.assertEqual(result["kind"], "proximity_route_graph")
        self.assertTrue(os.path.exists(prox_out))
        self.assertFalse(os.path.exists(prox_out + ".tmp"))
        # source edges preserved byte/value-identically vs the exact graph
        with open(graph_out, encoding="utf-8") as stream:
            exact = json.load(stream)
        self.assertEqual(result["edges"], exact["edges"])
        self.assertEqual(result["accounting"]["lengths"],
                         exact["accounting"]["lengths"])

    def test_dispatch_build_anchors_writes_atomically(self):
        data_dir = tempfile.mkdtemp()
        helpers.write_snapshot(data_dir, SNAPSHOT_SHA, helpers.standard_route_counts(), list(range(1, 89)))
        parser = build_parser()
        normalized = os.path.join(data_dir, "normalized.json")
        inventory = os.path.join(data_dir, "inventory.json")
        graph_out = os.path.join(data_dir, "graph.json")
        prox_out = os.path.join(data_dir, "graph-proximity.json")
        anchors_out = os.path.join(data_dir, "graph-anchors.json")
        dispatch(parser.parse_args(["normalize", "--snapshot", "current",
                                    "--data-dir", data_dir, "--output", normalized]))
        dispatch(parser.parse_args(["topology-inventory", "--input", normalized,
                                    "--output", inventory]))
        dispatch(parser.parse_args(["build-graph", "--input", normalized,
                                    "--inventory", inventory, "--output", graph_out]))
        dispatch(parser.parse_args(["apply-proximity", "--graph", graph_out,
                                    "--inventory", inventory, "--input", normalized,
                                    "--output", prox_out]))
        result = dispatch(parser.parse_args(["build-anchors", "--graph", prox_out,
                                             "--input", normalized,
                                             "--output", anchors_out]))
        self.assertEqual(result["kind"], "anchored_route_graph")
        self.assertTrue(os.path.exists(anchors_out))
        self.assertFalse(os.path.exists(anchors_out + ".tmp"))
        # all 88 temples accounted and explicitly statused
        self.assertEqual(result["accounting"]["temple_anchors"], 88)
        self.assertEqual(len(result["temple_anchors"]), 88)
        self.assertTrue(all(t["status"] in ("near", "offset", "review_required")
                            for t in result["temple_anchors"]))
        # source edges preserved byte/value-identically vs the proximity graph
        with open(prox_out, encoding="utf-8") as stream:
            prox = json.load(stream)
        self.assertEqual(result["edges"], prox["edges"])
        self.assertEqual(result["accounting"]["lengths"],
                         prox["accounting"]["lengths"])
        self.assertEqual(result["accounting"]["components_before"],
                         result["accounting"]["components_after"])

    def test_dispatch_build_sections_writes_atomically(self):
        data_dir = tempfile.mkdtemp()
        helpers.write_snapshot(data_dir, SNAPSHOT_SHA, helpers.standard_route_counts(), list(range(1, 89)))
        parser = build_parser()
        normalized = os.path.join(data_dir, "normalized.json")
        inventory = os.path.join(data_dir, "inventory.json")
        graph_out = os.path.join(data_dir, "graph.json")
        prox_out = os.path.join(data_dir, "graph-proximity.json")
        anchors_out = os.path.join(data_dir, "graph-anchors.json")
        sections_out = os.path.join(data_dir, "temple-sections.json")
        dispatch(parser.parse_args(["normalize", "--snapshot", "current",
                                    "--data-dir", data_dir, "--output", normalized]))
        dispatch(parser.parse_args(["topology-inventory", "--input", normalized,
                                    "--output", inventory]))
        dispatch(parser.parse_args(["build-graph", "--input", normalized,
                                    "--inventory", inventory, "--output", graph_out]))
        dispatch(parser.parse_args(["apply-proximity", "--graph", graph_out,
                                    "--inventory", inventory, "--input", normalized,
                                    "--output", prox_out]))
        dispatch(parser.parse_args(["build-anchors", "--graph", prox_out,
                                    "--input", normalized,
                                    "--output", anchors_out]))
        result = dispatch(parser.parse_args(["build-sections", "--input", anchors_out,
                                             "--output", sections_out]))
        self.assertEqual(result["kind"], "temple_sections")
        self.assertEqual(result["closure_88_1"], {"status": "not_requested"})
        self.assertEqual(result["accounting"]["sections_total"], 87)
        self.assertTrue(os.path.exists(sections_out))
        self.assertFalse(os.path.exists(sections_out + ".tmp"))

    def test_dispatch_build_section_corridors_writes_atomically(self):
        data_dir = tempfile.mkdtemp()
        helpers.write_snapshot(data_dir, SNAPSHOT_SHA, helpers.standard_route_counts(), list(range(1, 89)))
        parser = build_parser()
        normalized = os.path.join(data_dir, "normalized.json")
        inventory = os.path.join(data_dir, "inventory.json")
        graph_out = os.path.join(data_dir, "graph.json")
        prox_out = os.path.join(data_dir, "graph-proximity.json")
        anchors_out = os.path.join(data_dir, "graph-anchors.json")
        corridors_out = os.path.join(data_dir, "section-corridors.json")
        geojson_out = os.path.join(data_dir, "section-corridor-edges.geojson")
        dispatch(parser.parse_args(["normalize", "--snapshot", "current",
                                    "--data-dir", data_dir, "--output", normalized]))
        dispatch(parser.parse_args(["topology-inventory", "--input", normalized,
                                    "--output", inventory]))
        dispatch(parser.parse_args(["build-graph", "--input", normalized,
                                    "--inventory", inventory, "--output", graph_out]))
        dispatch(parser.parse_args(["apply-proximity", "--graph", graph_out,
                                    "--inventory", inventory, "--input", normalized,
                                    "--output", prox_out]))
        dispatch(parser.parse_args(["build-anchors", "--graph", prox_out,
                                    "--input", normalized,
                                    "--output", anchors_out]))
        result = dispatch(parser.parse_args(
            ["build-section-corridors", "--input", anchors_out,
             "--output", corridors_out, "--geojson", geojson_out]))
        self.assertEqual(result["kind"], "section_corridors")
        self.assertEqual(result["closure_88_1"], {"status": "not_requested"})
        self.assertEqual(result["accounting"]["sections_total"], 87)
        self.assertTrue(os.path.exists(corridors_out))
        self.assertTrue(os.path.exists(geojson_out))
        self.assertFalse(os.path.exists(corridors_out + ".tmp"))
        self.assertFalse(os.path.exists(geojson_out + ".tmp"))
        with open(geojson_out, encoding="utf-8") as stream:
            fc = json.load(stream)
        self.assertEqual(fc["type"], "FeatureCollection")
        ids = [f["id"] for f in fc["features"]]
        self.assertEqual(len(ids), len(set(ids)))

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