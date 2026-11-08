"""Consumer-visible regressions for static route extraction and source discovery."""
import copy
import json
import unittest

from datasets.ohenro_no_akari import downloader
from datasets.ohenro_no_akari.reference import build_web_reference as extractor


def feature(coordinates=None):
    return {"properties": {"_color": "#0000ff", "label": "brackets [ ] and braces { }"},
            "geometry": {"type": "LineString", "coordinates": coordinates or [[134, 34], [134.1, 34.1]]},
            "type": "Feature"}


def bundle(features):
    return "const renamed=" + json.dumps(features) + ";"


class StaticRouteTests(unittest.TestCase):
    def test_reordered_feature_keys_and_quoted_brackets_preserve_geometry(self):
        source = feature()
        collection, manifest = extractor.build_route(bundle([source]))
        self.assertEqual(collection["features"][0]["geometry"], source["geometry"])
        self.assertEqual(collection["features"][0]["properties"]["label"], source["properties"]["label"])
        self.assertEqual(manifest["accounting"]["point_count"], 2)
        self.assertGreater(manifest["accounting"]["total_length_m"], 14_000)
        extractor.validate_route(collection, manifest)

    def test_missing_truncated_and_ambiguous_arrays_cannot_extract(self):
        valid = bundle([feature()])
        for source in ("const unrelated=[];", valid[:-3], valid + "const second=" + json.dumps([feature()]) + ";"):
            with self.subTest(source=source[:35]), self.assertRaises(ValueError):
                extractor.build_route(source)

    def test_invalid_later_feature_is_not_silently_dropped(self):
        invalid = feature()
        invalid["geometry"] = {"type": "Point", "coordinates": [134, 34]}
        with self.assertRaises(ValueError):
            extractor.build_route(bundle([feature(), invalid]))
        with self.assertRaises(ValueError):
            extractor.build_route(bundle([feature()]) + bundle([invalid]))

    def test_invalid_coordinates_and_manifest_accounting_are_rejected(self):
        for coords in ([[True, 34], [134.1, 34.1]], [[134, float("nan")], [134.1, 34.1]],
                       [[140, 34], [134.1, 34.1]], [[134, 34], [134, 34]]):
            with self.subTest(coords=coords), self.assertRaises(ValueError):
                extractor.build_route(bundle([feature(coords)]))
        collection, manifest = extractor.build_route(bundle([feature()]))
        corrupt = copy.deepcopy(manifest)
        corrupt["accounting"]["point_count"] += 1
        with self.assertRaises(ValueError):
            extractor.validate_route(collection, corrupt)
        with self.assertRaises(ValueError):
            downloader.complete_route(collection, manifest)

    def test_comments_strings_and_js_key_syntax_do_not_create_fake_routes(self):
        source = '// const fake=[{type:"Feature"}];\nconst text="[{type:Feature}]";'
        source += "const route=[{type:'Feature',properties:{_opacity:.5},geometry:{type:'LineString',coordinates:[[134,34],[134.1,34.1]]}}];"
        collection, _ = extractor.build_route(source)
        self.assertEqual(collection["features"][0]["properties"]["_opacity"], 0.5)

    def test_deployment_html_and_bundle_names_do_not_change_route_identity(self):
        first, _ = extractor.build_route(bundle([feature()]), "https://app.henro-no-akari.com/assets/old.js")
        second, _ = extractor.build_route("const version='new';" + bundle([feature()]),
                                          "https://app.henro-no-akari.com/assets/new-123.js")
        self.assertEqual(downloader.identity(first), downloader.identity(second))


class ModuleDiscoveryTests(unittest.TestCase):
    def test_hashed_entrypoint_and_nested_static_dynamic_imports(self):
        roots = downloader.entrypoints('<script type="module" src="/assets/index-new123.js"></script>')
        self.assertEqual(roots, ["https://app.henro-no-akari.com/assets/index-new123.js"])
        imports = downloader.dependencies(
            'const quoteRegex=/["`]/g;'
            'import{a}from"./shared-99.js";import"./side-effect.js";'
            'const map=()=>import("./Map-new88.js");'
            '/* import("./fake.js") */ const label=\'import("./fake2.js")\';', roots[0])
        self.assertEqual(imports, ["https://app.henro-no-akari.com/assets/Map-new88.js",
                                   "https://app.henro-no-akari.com/assets/shared-99.js",
                                   "https://app.henro-no-akari.com/assets/side-effect.js"])

    def test_external_or_empty_app_graph_is_rejected(self):
        for html in ('<html>maintenance</html>', '<script type="module" src="https://other.example/app.js"></script>'):
            with self.subTest(html=html), self.assertRaises(ValueError):
                downloader.entrypoints(html)


if __name__ == "__main__":
    unittest.main()
