import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from datasets.omotenashi_henro_inspection import __main__ as source


KML = b'''<kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>Survey</name>
<Folder><name>North</name><Folder><name>Alternate</name><Placemark id="original">
<name>Inspection only</name><styleUrl>#blue</styleUrl><MultiGeometry>
<LineString><coordinates>134,34,12 134.1,34.1,13</coordinates></LineString>
<LineString><coordinates>133,33 133.1,33.1</coordinates></LineString>
</MultiGeometry></Placemark></Folder></Folder></Document></kml>'''


class TestPipeline(unittest.TestCase):
    def test_preserves_independent_lines_and_source_identity(self):
        collection = source.normalize(KML)
        self.assertEqual(len(collection['features']), 1)
        feature = collection['features'][0]
        self.assertEqual(feature['properties']['folders'], ['North', 'Alternate'])
        self.assertEqual(feature['properties']['documents'], ['Survey'])
        self.assertEqual(feature['properties']['source_placemark_id'], 'original')
        self.assertEqual(feature['properties']['name'], 'Inspection only')
        self.assertEqual(feature['properties']['purpose'], 'inspection_activity_route_coverage')
        self.assertEqual(feature['geometry'], {
            'type': 'MultiLineString',
            'coordinates': [[[134.0, 34.0, 12.0], [134.1, 34.1, 13.0]],
                            [[133.0, 33.0], [133.1, 33.1]]],
        })

    def test_rejects_invalid_or_unaccounted_source_geometry(self):
        for body in (KML.replace(b'134.1,34.1,13', b'134,34,12'),
                     KML.replace(b'134.1,34.1,13', b'nan,34,13'),
                     KML.replace(b'</Placemark>', b'<Point><coordinates>134,34</coordinates></Point></Placemark>'),
                     b'<kml><LineString><coordinates>134,34 134.1,34.1</coordinates></LineString></kml>',
                     b'<html>Server error</html>'):
            with self.subTest(body=body), self.assertRaises(ValueError):
                source.normalize(body)

    def test_discovers_changed_filename_from_current_official_map(self):
        map_url = 'https://komelabo.sakura.ne.jp/omotenashi-henro-walk/app/map/'
        pages = {
            source.SOURCE_PAGE_URL: f'<a href="{map_url}">Map</a>'.encode(),
            map_url: b'<script src="index.js"></script>',
            map_url + 'index.js': b'''let kmlDir = "../../kml/";
                // let routeKml = omnivore.kml(kmlDir + 'obsolete.kml');
                let routeKml = omnivore.kml(kmlDir + 'coverage2027.kml');
                let postKml = omnivore.kml(kmlDir + 'postoffice.kml');''',
        }
        with patch.object(source, '_download', side_effect=lambda url, timeout: (pages[url], 'text/html')):
            url, evidence = source.discover(30)
        self.assertEqual(url, 'https://komelabo.sakura.ne.jp/omotenashi-henro-walk/kml/coverage2027.kml')
        self.assertEqual([item['url'] for item in evidence], list(pages))

    def test_failed_refresh_keeps_selected_immutable_archive(self):
        with tempfile.TemporaryDirectory() as temporary:
            raw = Path(temporary)
            with patch.object(source, 'discover', return_value=(source.KML_URL, [])), \
                    patch.object(source, '_download', return_value=(KML, 'application/vnd.google-earth.kml+xml')):
                result = source.fetch(raw)
            current = (raw / 'current.json').read_bytes()
            snapshot = source.resolve(raw)
            metadata = (snapshot[0] / 'metadata.json').read_bytes()
            with patch.object(source, 'discover', return_value=(source.KML_URL, [])), \
                    patch.object(source, '_download', return_value=(b'<html>Error</html>', 'text/html')):
                with self.assertRaises(ValueError):
                    source.fetch(raw)
            self.assertEqual((raw / 'current.json').read_bytes(), current)
            self.assertEqual((snapshot[0] / 'metadata.json').read_bytes(), metadata)
            self.assertEqual(snapshot[2].read_bytes(), KML)
            self.assertEqual(source.resolve(raw)[1]['sha256'], result['sha256'])

    def test_tampered_output_is_rebuilt_and_coordinates_are_verified(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw, output, reports = (root / name for name in ('raw', 'output', 'reports'))
            with patch.object(source, 'discover', return_value=(source.KML_URL, [])), \
                    patch.object(source, '_download', return_value=(KML, 'application/vnd.google-earth.kml+xml')):
                source.fetch(raw)
            snapshot = source.resolve(raw)
            source.build(snapshot, output, reports)
            path = output / source.OUTPUTS[0]
            original = path.read_bytes()
            data = json.loads(original)
            data['features'][0]['geometry']['coordinates'][0][0][0] = 134.5
            path.write_text(json.dumps(data), encoding='utf-8')
            with self.assertRaises(ValueError):
                source.validate(output, reports, snapshot)
            source.build(snapshot, output, reports)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(source.validate(output, reports, snapshot)['line_count'], 2)
            before = path.stat().st_mtime_ns
            source.build(snapshot, output, reports)
            self.assertEqual(path.stat().st_mtime_ns, before)
