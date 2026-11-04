//! Rasterize merged meshes / DEM10 rasters into 256×256 tile accumulators.

use std::collections::HashMap;

use crate::gsi::model::GsiDemRaster;
use crate::raster::merged::{MergedMesh, SOURCE_NODATA};
use crate::tile::codec::quantize;
use crate::tile::grid::{ELEV_NODATA, TILE_SIZE, TileGrid};

/// In-memory accumulator for one tile (65536 cells).
#[derive(Debug, Clone)]
pub struct TileAcc {
    /// int16 meters, row-major north->south; `ELEV_NODATA` where empty.
    pub elevation: Box<[i16; TILE_SIZE * TILE_SIZE]>,
    /// plan §16 source code per cell; 0 where empty.
    pub source: Box<[u8; TILE_SIZE * TILE_SIZE]>,
    /// number of valid (non-empty) cells placed.
    pub cells: usize,
}

impl Default for TileAcc {
    fn default() -> Self {
        TileAcc {
            elevation: Box::new([ELEV_NODATA; TILE_SIZE * TILE_SIZE]),
            source: Box::new([0u8; TILE_SIZE * TILE_SIZE]),
            cells: 0,
        }
    }
}

/// Grid-aligned placement offsets of a raster's cells.
fn base_offset(r: &crate::raster::grid::GridBounds, grid: &TileGrid) -> (i64, i64) {
    let gx0 = ((r.min_lon - grid.origin_lon) / grid.step_lon).round() as i64;
    let gy0 = ((grid.origin_lat - r.max_lat) / grid.step_lat).round() as i64;
    (gx0, gy0)
}

/// Place a merged mesh's cells into tiles that belong to tile row `row_ty`.
///
/// A mesh spans at most two tile rows (150 < 256 cells), so callers invoke
/// this once per overlapping row; cells outside `row_ty` are skipped.
pub fn place_mesh(
    mesh: &MergedMesh,
    grid: &TileGrid,
    row_ty: i64,
    tiles: &mut HashMap<i64, TileAcc>,
) {
    let (gx0, gy0) = base_offset(&mesh.bounds, grid);
    let w = mesh.width;
    for row in 0..mesh.height {
        let gy = gy0 + row as i64;
        if gy.div_euclid(TILE_SIZE as i64) != row_ty {
            continue;
        }
        for col in 0..w {
            let idx = row * w + col;
            if mesh.source[idx] == SOURCE_NODATA {
                continue;
            }
            let gx = gx0 + col as i64;
            let (tx, _, px, py) = grid.tile_of(gx, gy);
            let t = tiles.entry(tx).or_default();
            let pos = py * TILE_SIZE + px;
            t.elevation[pos] = quantize(mesh.elevation[idx]);
            t.source[pos] = mesh.source[idx];
            t.cells += 1;
        }
    }
}

/// Place a DEM10B raster's cells (source code 1) into tile row `row_ty`.
pub fn place_dem10(
    r: &GsiDemRaster,
    grid: &TileGrid,
    row_ty: i64,
    tiles: &mut HashMap<i64, TileAcc>,
) {
    let (gx0, gy0) = base_offset(&crate::raster::grid::GridBounds::from_raster(r), grid);
    let w = r.width();
    for row in 0..r.height() {
        let gy = gy0 + row as i64;
        if gy.div_euclid(TILE_SIZE as i64) != row_ty {
            continue;
        }
        for col in 0..w {
            let idx = row * w + col;
            if r.mask[idx] == 0 {
                continue; // NODATA (DEM10B sea/nodata is `その他,-9999`)
            }
            let gx = gx0 + col as i64;
            let (tx, _, px, py) = grid.tile_of(gx, gy);
            let t = tiles.entry(tx).or_default();
            let pos = py * TILE_SIZE + px;
            t.elevation[pos] = quantize(r.elevation[idx]);
            t.source[pos] = 1;
            t.cells += 1;
        }
    }
}

#[cfg(test)]
mod tests {
    use std::io::Cursor;

    use crate::gsi::model::DemSource;
    use crate::gsi::xml::parse_dem;
    use crate::raster::merged::merge_rasters;

    use super::*;

    const STEP5: f64 = 1.0 / 18000.0;

    const DEM: &str = r#"<?xml version="1.0" encoding="UTF-8"?>
<Dataset xmlns:gml="http://www.opengis.net/gml/3.2" xmlns="http://fgd.gsi.go.jp/spec/2008/FGD_GMLSchema" gml:id="D">
<DEM gml:id="DEM001">
 <fid>fgoid:x-{MESH}</fid>
 <type>5mメッシュ（標高）</type>
 <mesh>{MESH}</mesh>
 <coverage gml:id="c">
  <gml:boundedBy>
   <gml:Envelope srsName="fguuid:jgd2024.bl">
    <gml:lowerCorner>34.5 134.25</gml:lowerCorner>
    <gml:upperCorner>34.508333333 134.2625</gml:upperCorner>
   </gml:Envelope>
  </gml:boundedBy>
  <gml:gridDomain>
   <gml:Grid dimension="2" gml:id="g">
    <gml:limits><gml:GridEnvelope>
      <gml:low>0 0</gml:low>
      <gml:high>2 1</gml:high>
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

    fn mesh(tuples: &str, name: &str) -> MergedMesh {
        let xml = DEM
            .replace("{MESH}", "51346200")
            .replace("{TUPLES}", tuples);
        let r = parse_dem(name, Cursor::new(xml)).unwrap();
        merge_rasters("51346200", &[(&DemSource::Dem5A, &r)]).unwrap()
    }

    #[test]
    fn places_cells_into_expected_tile() {
        let m = mesh(
            "地表面,100.5\n地表面,101.5\n地表面,102.5\n地表面,103.5\n地表面,104.5\n地表面,105.5",
            "FG-GML-5134-62-00-DEM5A-20251208.xml",
        );
        let grid = TileGrid::new(0.0, 0.0, STEP5, STEP5).from_bounds(
            m.bounds.min_lat,
            m.bounds.min_lon,
            m.bounds.max_lat,
            m.bounds.max_lon,
        );
        let mut tiles = HashMap::new();
        place_mesh(&m, &grid, 0, &mut tiles);
        // 3x2 mesh -> single tile (0,0), 6 cells
        assert_eq!(tiles.len(), 1);
        let t = &tiles[&0];
        assert_eq!(t.cells, 6);
        assert_eq!(t.elevation[0], 101); // NW cell quantized 100.5 -> 101
        assert_eq!(t.elevation[2], 103);
        assert_eq!(t.elevation[TILE_SIZE], 104);
        assert_eq!(t.elevation[TILE_SIZE + 2], 106);
        assert_eq!(t.source[0], 4);
    }

    #[test]
    fn nodata_cells_are_skipped() {
        let m = mesh(
            "地表面,100.5\nデータなし,-9999.\n地表面,102.5\n地表面,103.5\nデータなし,-9999.\n地表面,105.5",
            "FG-GML-5134-62-00-DEM5A-20251208.xml",
        );
        let grid = TileGrid::new(0.0, 0.0, STEP5, STEP5).from_bounds(
            m.bounds.min_lat,
            m.bounds.min_lon,
            m.bounds.max_lat,
            m.bounds.max_lon,
        );
        let mut tiles = HashMap::new();
        place_mesh(&m, &grid, 0, &mut tiles);
        let t = &tiles[&0];
        assert_eq!(t.cells, 4);
        assert_eq!(t.elevation[TILE_SIZE + 1], ELEV_NODATA);
        assert_eq!(t.source[TILE_SIZE + 1], 0);
    }
}
