//! Unit tests for per-mesh DEM5 merge (A > B > C pixel priority).

use std::io::Cursor;

use gsi_dem::gsi::model::{GsiDemRaster, SampleKind};
use gsi_dem::gsi::xml::parse_dem;
use gsi_dem::raster::merged::{
    MergedMesh, SOURCE_DEM5A, SOURCE_DEM5B, SOURCE_DEM5C, SOURCE_NODATA, merge_rasters,
};

/// 3x2 grid (row 0 = north), tuple order row-major (start 0 0):
/// row0: (0,0) (0,1) (0,2) ; row1: (1,0) (1,1) (1,2)
const BASE: &str = r#"<?xml version="1.0" encoding="UTF-8"?>
<Dataset xmlns:gml="http://www.opengis.net/gml/3.2" xmlns="http://fgd.gsi.go.jp/spec/2008/FGD_GMLSchema" gml:id="D">
<DEM gml:id="DEM001">
 <fid>fgoid:x-{MESH}</fid>
 <type>5mメッシュ（標高）</type>
 <mesh>{MESH}</mesh>
 <coverage gml:id="c">
  <gml:boundedBy>
   <gml:Envelope srsName="fguuid:jgd2024.bl">
    <gml:lowerCorner>{LAT1} {LON1}</gml:lowerCorner>
    <gml:upperCorner>{LAT2} {LON2}</gml:upperCorner>
   </gml:Envelope>
  </gml:boundedBy>
  <gml:gridDomain>
   <gml:Grid dimension="2" gml:id="g">
    <gml:limits><gml:GridEnvelope>
      <gml:low>0 0</gml:low>
      <gml:high>{HX} {HY}</gml:high>
    </gml:GridEnvelope></gml:limits>
    <gml:axisLabels>x y</gml:axisLabels>
   </gml:Grid>
  </gml:gridDomain>
  <gml:rangeSet><gml:DataBlock>
   <gml:rangeParameters><gml:QuantityList uom="DEM構成点"></gml:QuantityList></gml:rangeParameters>
<gml:tupleList>
{TUPLES}
</gml:tupleList>
  </gml:DataBlock></gml:rangeSet>
  <gml:coverageFunction><gml:GridFunction>
   <gml:sequenceRule order="+x-y">Linear</gml:sequenceRule>
   <gml:startPoint>{START}</gml:startPoint>
  </gml:GridFunction></gml:coverageFunction>
 </coverage>
</DEM>
</Dataset>
"#;

fn make(
    name: &str,
    tuples: &str,
    start: &str,
    high: &str,
    lat1: &str,
    lon1: &str,
    lat2: &str,
    lon2: &str,
) -> GsiDemRaster {
    let xml = BASE
        .replace("{MESH}", "51346200")
        .replace("{TUPLES}", tuples)
        .replace("{START}", start)
        .replace("{HX}", high.split_whitespace().next().unwrap())
        .replace("{HY}", high.split_whitespace().nth(1).unwrap())
        .replace("{LAT1}", lat1)
        .replace("{LON1}", lon1)
        .replace("{LAT2}", lat2)
        .replace("{LON2}", lon2);
    parse_dem(name, Cursor::new(xml)).unwrap()
}

fn terrain(vals: &[f32]) -> String {
    vals.iter()
        .map(|v| format!("地表面,{v}"))
        .collect::<Vec<_>>()
        .join("\n")
}

fn mix(items: &[(&str, &str)]) -> String {
    items
        .iter()
        .map(|(k, v)| format!("{k},{v}"))
        .collect::<Vec<_>>()
        .join("\n")
}

fn sample(m: &MergedMesh, row: usize, col: usize) -> gsi_dem::raster::merged::MergedSample {
    m.sample_at(row, col).unwrap()
}

#[test]
fn a_over_b_pixel_priority() {
    let a = make(
        "FG-GML-5134-62-00-DEM5A-20251208.xml",
        &terrain(&[10.0, 11.0, 12.0, 13.0, 14.0, 15.0]),
        "0 0",
        "2 1",
        "34.5",
        "134.25",
        "34.508333333",
        "134.2625",
    );
    let b = make(
        "FG-GML-5134-62-00-DEM5B-20250609.xml",
        &terrain(&[20.0; 6]),
        "0 0",
        "2 1",
        "34.5",
        "134.25",
        "34.508333333",
        "134.2625",
    );
    let m = merge_rasters(
        "51346200",
        &[
            (&gsi_dem::gsi::model::DemSource::Dem5B, &b),
            (&gsi_dem::gsi::model::DemSource::Dem5A, &a),
        ],
    )
    .unwrap();
    assert_eq!(m.width, 3);
    assert_eq!(m.height, 2);
    for (i, v) in [10.0, 11.0, 12.0, 13.0, 14.0, 15.0].iter().enumerate() {
        let row = i / 3;
        let col = i % 3;
        let s = sample(&m, row, col);
        assert_eq!(s.meters, Some(*v), "cell {row},{col}");
        assert_eq!(s.source_code, SOURCE_DEM5A);
    }
}

#[test]
fn a_nodata_falls_through_to_b() {
    let a = make(
        "FG-GML-5134-62-00-DEM5A-20251208.xml",
        &mix(&[
            ("地表面", "10"),
            ("データなし", "-9999."),
            ("地表面", "12"),
            ("地表面", "13"),
            ("データなし", "-9999."),
            ("地表面", "15"),
        ]),
        "0 0",
        "2 1",
        "34.5",
        "134.25",
        "34.508333333",
        "134.2625",
    );
    let b = make(
        "FG-GML-5134-62-00-DEM5B-20250609.xml",
        &terrain(&[20.0, 21.0, 22.0, 23.0, 24.0, 25.0]),
        "0 0",
        "2 1",
        "34.5",
        "134.25",
        "34.508333333",
        "134.2625",
    );
    let m = merge_rasters(
        "51346200",
        &[
            (&gsi_dem::gsi::model::DemSource::Dem5B, &b),
            (&gsi_dem::gsi::model::DemSource::Dem5A, &a),
        ],
    )
    .unwrap();
    assert_eq!(sample(&m, 0, 0).meters, Some(10.0));
    assert_eq!(sample(&m, 0, 1).meters, Some(21.0)); // B fills A nodata
    assert_eq!(sample(&m, 0, 1).source_code, SOURCE_DEM5B);
    assert_eq!(sample(&m, 0, 2).meters, Some(12.0));
    assert_eq!(sample(&m, 1, 1).meters, Some(24.0));
    assert_eq!(sample(&m, 1, 1).source_code, SOURCE_DEM5B);
    assert_eq!(sample(&m, 1, 2).meters, Some(15.0));
}

#[test]
fn sea_is_valid_and_wins_over_lower_priority() {
    // A marks cell (0,0) sea; B has terrain there. Sea must win (source A).
    let a = make(
        "FG-GML-5134-62-00-DEM5A-20251208.xml",
        &mix(&[
            ("海水面", "-9999."),
            ("地表面", "11"),
            ("地表面", "12"),
            ("地表面", "13"),
            ("地表面", "14"),
            ("地表面", "15"),
        ]),
        "0 0",
        "2 1",
        "34.5",
        "134.25",
        "34.508333333",
        "134.2625",
    );
    let b = make(
        "FG-GML-5134-62-00-DEM5B-20250609.xml",
        &terrain(&[100.0, 101.0, 102.0, 103.0, 104.0, 105.0]),
        "0 0",
        "2 1",
        "34.5",
        "134.25",
        "34.508333333",
        "134.2625",
    );
    let m = merge_rasters(
        "51346200",
        &[
            (&gsi_dem::gsi::model::DemSource::Dem5B, &b),
            (&gsi_dem::gsi::model::DemSource::Dem5A, &a),
        ],
    )
    .unwrap();
    let s = sample(&m, 0, 0);
    assert_eq!(s.kind, SampleKind::Sea);
    assert_eq!(s.meters, Some(0.0));
    assert_eq!(s.source_code, SOURCE_DEM5A);
    assert_eq!(sample(&m, 0, 1).meters, Some(11.0));
}

#[test]
fn partial_a_filled_by_b() {
    // A is partial: startPoint (2,1) -> single sample at cell (1,2) = 10.
    // B is full. Merged: (1,2)=A, everything else=B.
    let a = make(
        "FG-GML-5134-62-00-DEM5A-20251208.xml",
        "地表面,10",
        "2 1",
        "2 1",
        "34.5",
        "134.25",
        "34.508333333",
        "134.2625",
    );
    let b = make(
        "FG-GML-5134-62-00-DEM5B-20250609.xml",
        &terrain(&[20.0; 6]),
        "0 0",
        "2 1",
        "34.5",
        "134.25",
        "34.508333333",
        "134.2625",
    );
    let m = merge_rasters(
        "51346200",
        &[
            (&gsi_dem::gsi::model::DemSource::Dem5B, &b),
            (&gsi_dem::gsi::model::DemSource::Dem5A, &a),
        ],
    )
    .unwrap();
    let s = sample(&m, 1, 2);
    assert_eq!(s.meters, Some(10.0));
    assert_eq!(s.source_code, SOURCE_DEM5A);
    for (row, col) in [(0, 0), (0, 1), (0, 2), (1, 0), (1, 1)] {
        assert_eq!(sample(&m, row, col).meters, Some(20.0), "cell {row},{col}");
        assert_eq!(sample(&m, row, col).source_code, SOURCE_DEM5B);
    }
}

#[test]
fn c_is_lowest_priority() {
    let a = make(
        "FG-GML-5134-62-00-DEM5A-20251208.xml",
        &mix(&[("データなし", "-9999."); 6]),
        "0 0",
        "2 1",
        "34.5",
        "134.25",
        "34.508333333",
        "134.2625",
    );
    let b = make(
        "FG-GML-5134-62-00-DEM5B-20250609.xml",
        &mix(&[("データなし", "-9999."); 6]),
        "0 0",
        "2 1",
        "34.5",
        "134.25",
        "34.508333333",
        "134.2625",
    );
    let c = make(
        "FG-GML-5134-62-00-DEM5C-20250605.xml",
        &terrain(&[30.0; 6]),
        "0 0",
        "2 1",
        "34.5",
        "134.25",
        "34.508333333",
        "134.2625",
    );
    let m = merge_rasters(
        "51346200",
        &[
            (&gsi_dem::gsi::model::DemSource::Dem5C, &c),
            (&gsi_dem::gsi::model::DemSource::Dem5A, &a),
            (&gsi_dem::gsi::model::DemSource::Dem5B, &b),
        ],
    )
    .unwrap();
    for i in 0..6 {
        let (row, col) = (i / 3, i % 3);
        assert_eq!(sample(&m, row, col).meters, Some(30.0));
        assert_eq!(sample(&m, row, col).source_code, SOURCE_DEM5C);
    }
}

#[test]
fn single_source_only() {
    let b = make(
        "FG-GML-5134-62-00-DEM5B-20250609.xml",
        &terrain(&[1.0, 2.0, 3.0, 4.0, 5.0, 6.0]),
        "0 0",
        "2 1",
        "34.5",
        "134.25",
        "34.508333333",
        "134.2625",
    );
    let m = merge_rasters("51346200", &[(&gsi_dem::gsi::model::DemSource::Dem5B, &b)]).unwrap();
    assert_eq!(sample(&m, 1, 2).meters, Some(6.0));
    assert_eq!(sample(&m, 1, 2).source_code, SOURCE_DEM5B);
    assert_eq!(m.source_counts()[SOURCE_DEM5B as usize], 6);
}

#[test]
fn all_nodata_source_array() {
    let a = make(
        "FG-GML-5134-62-00-DEM5A-20251208.xml",
        &mix(&[("データなし", "-9999."); 6]),
        "0 0",
        "2 1",
        "34.5",
        "134.25",
        "34.508333333",
        "134.2625",
    );
    let m = merge_rasters("51346200", &[(&gsi_dem::gsi::model::DemSource::Dem5A, &a)]).unwrap();
    assert_eq!(m.source_counts()[SOURCE_NODATA as usize], 6);
    for i in 0..6 {
        let (row, col) = (i / 3, i % 3);
        assert!(sample(&m, row, col).meters.is_none());
        assert_eq!(sample(&m, row, col).source_code, SOURCE_NODATA);
    }
}

#[test]
fn empty_rasters_is_error() {
    assert!(merge_rasters("51346200", &[]).is_err());
}

#[test]
fn conflicting_geometry_is_error() {
    let a = make(
        "FG-GML-5134-62-00-DEM5A-20251208.xml",
        &terrain(&[10.0; 6]),
        "0 0",
        "2 1",
        "34.5",
        "134.25",
        "34.508333333",
        "134.2625",
    );
    // different envelope (B covers a different area)
    let b = make(
        "FG-GML-5134-62-00-DEM5B-20250609.xml",
        &terrain(&[20.0; 6]),
        "0 0",
        "2 1",
        "34.6",
        "134.25",
        "34.608333333",
        "134.2625",
    );
    let err = merge_rasters(
        "51346200",
        &[
            (&gsi_dem::gsi::model::DemSource::Dem5B, &b),
            (&gsi_dem::gsi::model::DemSource::Dem5A, &a),
        ],
    )
    .unwrap_err();
    assert!(err.to_string().contains("conflicting grid geometry"));
}

#[test]
fn partial_last_row_regression() {
    // Real-data case: mesh stored 5039/33750 with start=(13,0) — the last
    // stored row is partial. Cells past the stored region map to an index
    // >= sample_count and must be treated as "no sample from this source".
    // 3x2 grid, start (2,0): stored tuples cover (0,2) and (1,0) only.
    let a = make(
        "FG-GML-5134-62-00-DEM5A-20251208.xml",
        "地表面,10\n地表面,11",
        "2 0",
        "2 1",
        "34.5",
        "134.25",
        "34.508333333",
        "134.2625",
    );
    assert_eq!(a.sample_count(), 2);
    let b = make(
        "FG-GML-5134-62-00-DEM5B-20250609.xml",
        &terrain(&[20.0; 6]),
        "0 0",
        "2 1",
        "34.5",
        "134.25",
        "34.508333333",
        "134.2625",
    );
    let m = merge_rasters(
        "51346200",
        &[
            (&gsi_dem::gsi::model::DemSource::Dem5B, &b),
            (&gsi_dem::gsi::model::DemSource::Dem5A, &a),
        ],
    )
    .unwrap();
    assert_eq!(sample(&m, 0, 2).meters, Some(10.0));
    assert_eq!(sample(&m, 0, 2).source_code, SOURCE_DEM5A);
    assert_eq!(sample(&m, 1, 0).meters, Some(11.0));
    assert_eq!(sample(&m, 1, 0).source_code, SOURCE_DEM5A);
    for (row, col) in [(0, 0), (0, 1), (1, 1), (1, 2)] {
        assert_eq!(sample(&m, row, col).meters, Some(20.0), "cell {row},{col}");
        assert_eq!(sample(&m, row, col).source_code, SOURCE_DEM5B);
    }
}

#[test]
fn seabed_wins_over_lower_priority_and_keeps_value() {
    // A marks cell (0,0) as seabed (-5.16m, real elevation); B has terrain
    // there. Seabed is valid and must win, preserving the negative value.
    let a = make(
        "FG-GML-5134-62-00-DEM5A-20251208.xml",
        &mix(&[
            ("海水底面", "-5.16"),
            ("地表面", "11"),
            ("地表面", "12"),
            ("地表面", "13"),
            ("地表面", "14"),
            ("地表面", "15"),
        ]),
        "0 0",
        "2 1",
        "34.5",
        "134.25",
        "34.508333333",
        "134.2625",
    );
    let b = make(
        "FG-GML-5134-62-00-DEM5B-20250609.xml",
        &terrain(&[100.0; 6]),
        "0 0",
        "2 1",
        "34.5",
        "134.25",
        "34.508333333",
        "134.2625",
    );
    let m = merge_rasters(
        "51346200",
        &[
            (&gsi_dem::gsi::model::DemSource::Dem5B, &b),
            (&gsi_dem::gsi::model::DemSource::Dem5A, &a),
        ],
    )
    .unwrap();
    let s = sample(&m, 0, 0);
    assert_eq!(s.kind, SampleKind::Seabed);
    assert_eq!(s.meters, Some(-5.16));
    assert_eq!(s.source_code, SOURCE_DEM5A);
}

#[test]
fn merged_lookup_round_trip() {
    let a = make(
        "FG-GML-5134-62-00-DEM5A-20251208.xml",
        &terrain(&[10.0, 11.0, 12.0, 13.0, 14.0, 15.0]),
        "0 0",
        "2 1",
        "34.5",
        "134.25",
        "34.508333333",
        "134.2625",
    );
    let m = merge_rasters("51346200", &[(&gsi_dem::gsi::model::DemSource::Dem5A, &a)]).unwrap();
    let (lat, lon) = m.cell_center(0, 0);
    let (row, col) = m.nearest_cell(lat, lon).unwrap();
    assert_eq!((row, col), (0, 0));
    assert_eq!(sample(&m, row, col).meters, Some(10.0));
    assert_eq!(m.kind_counts()[1].1, 6); // 6 terrain
}
