//! DEM10B fallback layer helpers (plan §17 / §42 Phase 4).
//!
//! DEM10B is kept as an independent, coarser-resolution layer (10m vs 5m)
//! — it is never resampled or merged into DEM5. At query time the runtime
//! asks DEM5 first and falls back to DEM10B only where DEM5 has no value.

use crate::gsi::model::{GsiDemRaster, SampleKind};
use crate::raster::grid::{nearest_cell, sample_at};
use crate::raster::merged::{MergedMesh, SOURCE_NODATA};

/// Elevation from a DEM10B raster at a lat/lon (nearest-cell).
///
/// Returns `None` when the point is outside the raster or the covering cell
/// has no data. DEM10B carries no sea semantics (`その他,-9999` is nodata),
/// so only terrain cells are valid.
pub fn dem10_elevation(r: &GsiDemRaster, lat: f64, lon: f64) -> Option<f32> {
    let (row, col) = nearest_cell(r, lat, lon)?;
    let s = sample_at(r, row, col)?;
    match s.kind {
        SampleKind::Terrain => s.meters,
        _ => None,
    }
}

/// Count the DEM5 merged mesh's nodata cells that a DEM10B raster covers.
///
/// Every DEM5-nodata grid cell is turned into its center lat/lon and
/// sampled against the (coarser) DEM10B raster. Returns
/// `(fills, remains)` where `fills + remains == nodata cell count`.
pub fn dem10_fill_count(merged: &MergedMesh, dem10: &GsiDemRaster) -> (usize, usize) {
    let mut fills = 0usize;
    let mut remains = 0usize;
    for row in 0..merged.height {
        for col in 0..merged.width {
            if merged.source[row * merged.width + col] != SOURCE_NODATA {
                continue;
            }
            let (lat, lon) = merged.cell_center(row, col);
            if dem10_elevation(dem10, lat, lon).is_some() {
                fills += 1;
            } else {
                remains += 1;
            }
        }
    }
    (fills, remains)
}

#[cfg(test)]
mod tests {
    use std::io::Cursor;

    use crate::gsi::model::GsiDemRaster;
    use crate::gsi::xml::parse_dem;

    use super::*;

    const DEM10: &str = r#"<?xml version="1.0" encoding="UTF-8"?>
<Dataset xmlns:gml="http://www.opengis.net/gml/3.2" xmlns="http://fgd.gsi.go.jp/spec/2008/FGD_GMLSchema" gml:id="D">
<DEM gml:id="DEM001">
 <fid>fgoid:x-5134-62</fid>
 <type>10mメッシュ（標高）</type>
 <mesh>513462</mesh>
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
   <gml:tupleList>
{TUPLES}
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

    fn make_dem10(
        tuples: &str,
        high: &str,
        lat1: &str,
        lon1: &str,
        lat2: &str,
        lon2: &str,
    ) -> GsiDemRaster {
        let hx = high.split_whitespace().next().unwrap();
        let hy = high.split_whitespace().nth(1).unwrap();
        let xml = DEM10
            .replace("{LAT1}", lat1)
            .replace("{LON1}", lon1)
            .replace("{LAT2}", lat2)
            .replace("{LON2}", lon2)
            .replace("{HX}", hx)
            .replace("{HY}", hy)
            .replace("{TUPLES}", tuples);
        parse_dem("FG-GML-5134-62-dem10b-20161001.xml", Cursor::new(xml)).unwrap()
    }

    #[test]
    fn dem10_elevation_returns_terrain_only() {
        // 3x2 DEM10B grid, all terrain.
        let r = make_dem10(
            "その他,120.5\nその他,121.5\nその他,122.5\nその他,123.5\nその他,124.5\nその他,125.5",
            "2 1",
            "34.5",
            "134.25",
            "34.508333333",
            "134.2625",
        );
        // center of cell (0,0) = max_lat - 0.5*step_lat, min_lon + 0.5*step_lon
        let lat = 34.508333333 - 0.5 * (34.508333333 - 34.5) / 2.0;
        let lon = 134.25 + 0.5 * (134.2625 - 134.25) / 3.0;
        assert_eq!(dem10_elevation(&r, lat, lon), Some(120.5));
        // outside bounds
        assert_eq!(dem10_elevation(&r, 34.6, 134.2), None);
    }

    #[test]
    fn dem10_nodata_is_not_elevation() {
        let r = make_dem10(
            "その他,-9999.00\nその他,121.5\nその他,122.5\nその他,123.5\nその他,124.5\nその他,125.5",
            "2 1",
            "34.5",
            "134.25",
            "34.508333333",
            "134.2625",
        );
        let lat = 34.508333333 - 0.5 * (34.508333333 - 34.5) / 2.0;
        let lon = 134.25 + 0.5 * (134.2625 - 134.25) / 3.0;
        assert_eq!(dem10_elevation(&r, lat, lon), None);
    }

    fn merged_with_nodata() -> MergedMesh {
        MergedMesh {
            mesh: "51346200".to_string(),
            bounds: crate::raster::grid::GridBounds {
                min_lat: 34.5,
                min_lon: 134.25,
                max_lat: 34.508333333,
                max_lon: 134.2625,
            },
            width: 3,
            height: 2,
            // row-major north->south; nodata at (0,1) and (1,1)
            elevation: vec![1.0, f32::NAN, 3.0, 4.0, f32::NAN, 6.0],
            mask: vec![1, 0, 1, 1, 0, 1],
            source: vec![4, 0, 4, 4, 0, 4],
        }
    }

    #[test]
    fn dem10_fill_count_fills_terrain_gaps() {
        let dem10 = make_dem10(
            "その他,120.5\nその他,121.5\nその他,122.5\nその他,123.5\nその他,124.5\nその他,125.5",
            "2 1",
            "34.5",
            "134.25",
            "34.508333333",
            "134.2625",
        );
        let m = merged_with_nodata();
        let (fills, remains) = dem10_fill_count(&m, &dem10);
        assert_eq!((fills, remains), (2, 0));
    }

    #[test]
    fn dem10_fill_count_respects_dem10_gaps() {
        // DEM10B has nodata where the DEM5 mesh has nodata.
        let dem10 = make_dem10(
            "その他,120.5\nその他,-9999.00\nその他,122.5\nその他,123.5\nその他,-9999.00\nその他,125.5",
            "2 1",
            "34.5",
            "134.25",
            "34.508333333",
            "134.2625",
        );
        let m = merged_with_nodata();
        let (fills, remains) = dem10_fill_count(&m, &dem10);
        assert_eq!((fills, remains), (0, 2));
    }
}
