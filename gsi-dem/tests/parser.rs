//! Unit tests for the GSI DEM XML parser using a synthetic fixture.
//!
//! A small 3x2 grid is used so tuple-index <-> grid placement can be
//! verified by hand.

use std::io::Cursor;

use gsi_dem::gsi::model::SampleKind;
use gsi_dem::gsi::xml::parse_dem;

const SMALL_DEM: &str = r#"<?xml version="1.0" encoding="UTF-8"?>
<Dataset xmlns:gml="http://www.opengis.net/gml/3.2" xmlns="http://fgd.gsi.go.jp/spec/2008/FGD_GMLSchema" gml:id="Dataset1">
<DEM gml:id="DEM001">
 <fid>fgoid:10-00100-25-60101-51346200</fid>
 <lfSpanFr gml:id="DEM001-1"><gml:timePosition>2025-12-08</gml:timePosition></lfSpanFr>
 <type>5mメッシュ（標高）</type>
 <mesh>51346200</mesh>
 <coverage gml:id="DEM001-3">
  <gml:boundedBy>
   <gml:Envelope srsName="fguuid:jgd2024.bl">
    <gml:lowerCorner>34.5 134.25</gml:lowerCorner>
    <gml:upperCorner>34.508333333 134.2625</gml:upperCorner>
   </gml:Envelope>
  </gml:boundedBy>
  <gml:gridDomain>
   <gml:Grid dimension="2" gml:id="DEM001-4">
    <gml:limits><gml:GridEnvelope>
      <gml:low>0 0</gml:low>
      <gml:high>2 1</gml:high>
    </gml:GridEnvelope></gml:limits>
    <gml:axisLabels>x y</gml:axisLabels>
   </gml:Grid>
  </gml:gridDomain>
  <gml:rangeSet><gml:DataBlock>
   <gml:rangeParameters><gml:QuantityList uom="DEM構成点"></gml:QuantityList></gml:rangeParameters>
<gml:tupleList>
地表面,100.5
海水面,-9999.
データなし,-9999.
地表面,200.5
内水面,50.5
データなし,-9999.
</gml:tupleList>
  </gml:DataBlock></gml:rangeSet>
  <gml:coverageFunction><gml:GridFunction>
   <gml:sequenceRule order="+x-y">Linear</gml:sequenceRule>
   <gml:startPoint>0 0</gml:startPoint>
  </gml:GridFunction></gml:coverageFunction>
 </coverage>
</DEM>
</Dataset>
"#;

#[test]
fn parses_metadata() {
    let r = parse_dem(
        "FG-GML-5134-62-00-DEM5A-20251208.xml",
        Cursor::new(SMALL_DEM),
    )
    .unwrap();
    assert_eq!(r.mesh, "51346200");
    assert_eq!(r.source.as_str(), "DEM5A");
    assert_eq!(r.survey_date, "2025-12-08");
    assert_eq!(r.type_label, "5mメッシュ（標高）");
    assert_eq!(r.crs, "fguuid:jgd2024.bl");
    assert_eq!(r.lower_lat, 34.5);
    assert_eq!(r.lower_lon, 134.25);
    assert_eq!(r.upper_lat, 34.508333333);
    assert_eq!(r.upper_lon, 134.2625);
    assert_eq!(r.width(), 3);
    assert_eq!(r.height(), 2);
    assert_eq!(r.sequence_order, "+x-y");
    assert_eq!(r.start_x, 0);
    assert_eq!(r.start_y, 0);
}

#[test]
fn parses_sample_kinds() {
    let r = parse_dem(
        "FG-GML-5134-62-00-DEM5A-20251208.xml",
        Cursor::new(SMALL_DEM),
    )
    .unwrap();
    assert_eq!(r.sample_count(), 6);
    assert_eq!(r.mask[0], SampleKind::Terrain as u8);
    assert_eq!(r.elevation[0], 100.5);
    assert_eq!(r.mask[1], SampleKind::Sea as u8);
    assert_eq!(r.elevation[1], 0.0); // sea normalized to 0
    assert_eq!(r.mask[2], SampleKind::NoData as u8);
    assert!(r.elevation[2].is_nan());
    assert_eq!(r.mask[3], SampleKind::Terrain as u8);
    assert_eq!(r.mask[4], SampleKind::InlandWater as u8);
    assert_eq!(r.elevation[4], 50.5);
    assert_eq!(r.mask[5], SampleKind::NoData as u8);
}

#[test]
fn dem10b_sentinel_label() {
    // DEM10B uses `その他` with -9999.00 sentinel
    let xml = SMALL_DEM
        .replace("地表面,100.5", "その他,100.5")
        .replace("海水面,-9999.", "その他,-9999.00")
        .replace("データなし,-9999.", "その他,-9999.00");
    let r = parse_dem("FG-GML-5134-62-dem10b-20161001.xml", Cursor::new(xml)).unwrap();
    assert_eq!(r.mask[0], SampleKind::Terrain as u8);
    assert_eq!(r.mask[1], SampleKind::NoData as u8);
    assert_eq!(r.mask[2], SampleKind::NoData as u8);
}

#[test]
fn negative_and_decimal_elevations() {
    let xml = SMALL_DEM
        .replace("地表面,100.5", "地表面,-0.17")
        .replace("海水面,-9999.", "地表面,-0.17")
        .replace("データなし,-9999.", "地表面,-0.17")
        .replace("地表面,200.5", "地表面,-0.27");
    let r = parse_dem("FG-GML-5134-62-00-DEM5A-20251208.xml", Cursor::new(xml)).unwrap();
    assert_eq!(r.mask[0], SampleKind::Terrain as u8);
    assert_eq!(r.elevation[0], -0.17);
    assert_eq!(r.mask[3], SampleKind::Terrain as u8);
    assert_eq!(r.elevation[3], -0.27);
}

#[test]
fn grid_placement_full_grid() {
    use gsi_dem::raster::grid::{grid_to_tuple_index, sample_at, tuple_index_to_grid};
    let r = parse_dem(
        "FG-GML-5134-62-00-DEM5A-20251208.xml",
        Cursor::new(SMALL_DEM),
    )
    .unwrap();
    // Full grid (start 0,0), width 3, height 2, row-major north->south.
    // tuple index 0 = (row 0, col 0), index 3 = (row 1, col 0).
    assert_eq!(tuple_index_to_grid(&r, 0), Some((0, 0)));
    assert_eq!(tuple_index_to_grid(&r, 1), Some((0, 1)));
    assert_eq!(tuple_index_to_grid(&r, 3), Some((1, 0)));
    assert_eq!(grid_to_tuple_index(&r, 0, 2), Some(2));
    assert_eq!(grid_to_tuple_index(&r, 1, 2), Some(5));

    let s = sample_at(&r, 0, 0).unwrap();
    assert_eq!(s.kind, SampleKind::Terrain);
    assert_eq!(s.meters, Some(100.5));
}

#[test]
fn grid_placement_partial_grid() {
    use gsi_dem::raster::grid::{grid_to_tuple_index, tuple_index_to_grid};
    // startPoint (2, 1): first row (y=1) covers x=2..2 (1 sample),
    // then full rows y=2..2? height is 2 so only y=1.
    let xml = SMALL_DEM.replace(
        "<gml:startPoint>0 0</gml:startPoint>",
        "<gml:startPoint>2 1</gml:startPoint>",
    );
    let r = parse_dem("FG-GML-5134-62-00-DEM5A-20251208.xml", Cursor::new(xml)).unwrap();
    // width 3, height 2, start (2,1): first row has 3-2=1 sample at (1,2).
    assert_eq!(tuple_index_to_grid(&r, 0), Some((1, 2)));
    assert_eq!(grid_to_tuple_index(&r, 1, 2), Some(0));
    // cells not covered -> None
    assert_eq!(grid_to_tuple_index(&r, 0, 0), None);
    assert_eq!(grid_to_tuple_index(&r, 0, 1), None);
    assert_eq!(grid_to_tuple_index(&r, 1, 0), None);
    assert_eq!(grid_to_tuple_index(&r, 1, 1), None);
}

#[test]
fn cell_center_north_up() {
    use gsi_dem::raster::grid::cell_center;
    let r = parse_dem(
        "FG-GML-5134-62-00-DEM5A-20251208.xml",
        Cursor::new(SMALL_DEM),
    )
    .unwrap();
    // bounds: lat 34.5..34.5083333 (2 rows), lon 134.25..134.2625 (3 cols)
    // (row 0, col 0) = NW cell center = max_lat - 0.5*step_lat, min_lon + 0.5*step_lon
    let (lat, lon) = cell_center(&r, 0, 0);
    let lat_step = (34.508333333 - 34.5) / 2.0;
    let lon_step = (134.2625 - 134.25) / 3.0;
    assert!((lat - (34.508333333 - 0.5 * lat_step)).abs() < 1e-9);
    assert!((lon - (134.25 + 0.5 * lon_step)).abs() < 1e-9);
}

#[test]
fn unknown_tuple_kind_is_error() {
    let xml = SMALL_DEM.replace("データなし,-9999.", "未知のラベル,1.0");
    let err = parse_dem("FG-GML-5134-62-00-DEM5A-20251208.xml", Cursor::new(xml)).unwrap_err();
    assert!(err.to_string().contains("unknown tuple kind"));
}

#[test]
fn invalid_elevation_is_error() {
    let xml = SMALL_DEM.replace("地表面,100.5", "地表面,abc");
    let err = parse_dem("FG-GML-5134-62-00-DEM5A-20251208.xml", Cursor::new(xml)).unwrap_err();
    assert!(err.to_string().contains("invalid elevation"));
}

#[test]
fn seabed_kind_with_real_negative_elevation() {
    // `海水底面` (seabed) carries a real measured elevation (e.g. -5.16m),
    // unlike `海水面` which is the -9999 sentinel. It must keep its value.
    let xml = SMALL_DEM.replace("海水面,-9999.", "海水底面,-5.16");
    let r = parse_dem("FG-GML-5134-62-00-DEM5A-20251208.xml", Cursor::new(xml)).unwrap();
    assert_eq!(r.mask[1], SampleKind::Seabed as u8);
    assert_eq!(r.elevation[1], -5.16);
}

#[test]
fn inland_bottom_kind_with_real_elevation() {
    // `内水底面` (inland water bed) likewise carries a real elevation.
    let xml = SMALL_DEM.replace("内水面,50.5", "内水底面,12.3");
    let r = parse_dem("FG-GML-5134-62-00-DEM5A-20251208.xml", Cursor::new(xml)).unwrap();
    assert_eq!(r.mask[4], SampleKind::InlandBottom as u8);
    assert_eq!(r.elevation[4], 12.3);
}

#[test]
fn shift_jis_archive_decodes_labels() {
    // Legacy 2008-2010 DEM5B archives declare encoding="Shift_JIS".
    let (bytes, _, _) = encoding_rs::SHIFT_JIS.encode(SMALL_DEM);
    let mut bytes = bytes.into_owned();
    // swap the (ASCII) encoding declaration; Japanese text stays as
    // Shift_JIS bytes
    let decl = b"encoding=\"UTF-8\"";
    let pos = bytes
        .windows(decl.len())
        .position(|w| w == decl)
        .expect("decl");
    bytes.splice(
        pos..pos + decl.len(),
        b"encoding=\"Shift_JIS\"".iter().copied(),
    );
    let r = parse_dem("FG-GML-5134-40-31-dem5b-20080331.xml", Cursor::new(bytes)).unwrap();
    assert_eq!(r.mesh, "51346200");
    assert_eq!(r.source.as_str(), "DEM5B");
    assert_eq!(r.type_label, "5mメッシュ（標高）");
    assert_eq!(r.mask[0], SampleKind::Terrain as u8);
    assert_eq!(r.elevation[0], 100.5);
    assert_eq!(r.mask[1], SampleKind::Sea as u8);
    assert_eq!(r.mask[2], SampleKind::NoData as u8);
    assert!(r.elevation[2].is_nan());
}

#[test]
fn parse_meta_stops_at_tuple_list() {
    use gsi_dem::gsi::xml::parse_dem_meta;
    let meta = parse_dem_meta(
        "FG-GML-5134-62-00-DEM5A-20251208.xml",
        Cursor::new(SMALL_DEM),
    )
    .unwrap();
    assert_eq!(meta.mesh, "51346200");
    assert_eq!(meta.source.as_str(), "DEM5A");
    assert_eq!(meta.survey_date, "2025-12-08");
}
