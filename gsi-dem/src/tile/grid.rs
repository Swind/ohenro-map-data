//! Geographic fixed-grid tiling model (plan §19/§24).
//!
//! The whole dataset lives on a uniform lat/lon grid per layer:
//!
//! - DEM5  layer: `step = 1/18000°` (~6.2 m) — verified that every GSI 3次
//!   mesh corner is exactly on this grid (bounds × 18000 are integers).
//! - DEM10 layer: `step = 1/9000°` (~12.4 m) — its 1125×750 region rasters
//!   also align to the shared 1/18000° grid (every 2nd cell).
//!
//! `origin` is the grid-aligned north-west corner covering all data, so all
//! cell coordinates are non-negative. Tiles are 256×256 cells; GSI mesh
//! boundaries (150×225 cells) do not constrain the tile grid.

/// Cells per tile edge.
pub const TILE_SIZE: usize = 256;

/// int16 sentinel for no elevation data (plan §20).
pub const ELEV_NODATA: i16 = i16::MIN;

/// Global grid for one layer.
#[derive(Debug, Clone, Copy)]
pub struct TileGrid {
    /// Latitude of the grid's northern edge (row 0).
    pub origin_lat: f64,
    /// Longitude of the grid's western edge (column 0).
    pub origin_lon: f64,
    /// Degrees per cell, north-south.
    pub step_lat: f64,
    /// Degrees per cell, east-west.
    pub step_lon: f64,
}

impl TileGrid {
    pub fn new(origin_lat: f64, origin_lon: f64, step_lat: f64, step_lon: f64) -> TileGrid {
        TileGrid {
            origin_lat,
            origin_lon,
            step_lat,
            step_lon,
        }
    }

    /// Align `origin` to the grid so the box `[min_lat,min_lon,max_lat,max_lon]`
    /// is fully covered with non-negative cell coordinates. Only the north-west
    /// corner (`max_lat`, `min_lon`) matters; the rest bounds the extent.
    pub fn from_bounds(
        &self,
        _min_lat: f64,
        min_lon: f64,
        max_lat: f64,
        _max_lon: f64,
    ) -> TileGrid {
        TileGrid {
            origin_lat: (max_lat / self.step_lat).ceil() * self.step_lat,
            origin_lon: (min_lon / self.step_lon).floor() * self.step_lon,
            ..*self
        }
    }

    /// Global cell coordinates of a lat/lon (north-up). Cell centers sit at
    /// half-integer offsets from the origin, so `floor` gives the cell index.
    pub fn global_cell(&self, lat: f64, lon: f64) -> (i64, i64) {
        let gy = ((self.origin_lat - lat) / self.step_lat).floor() as i64;
        let gx = ((lon - self.origin_lon) / self.step_lon).floor() as i64;
        (gx, gy)
    }

    /// Global cell range `(max_x, max_y)` covered by a box (exclusive upper).
    pub fn cell_extent(
        &self,
        min_lat: f64,
        _min_lon: f64,
        _max_lat: f64,
        max_lon: f64,
    ) -> (i64, i64) {
        let gx = ((max_lon - self.origin_lon) / self.step_lon).ceil() as i64;
        let gy = ((self.origin_lat - min_lat) / self.step_lat).ceil() as i64;
        (gx, gy)
    }

    /// Decompose a global cell into (tile_x, tile_y, pixel_x, pixel_y).
    pub fn tile_of(&self, gx: i64, gy: i64) -> (i64, i64, usize, usize) {
        let tx = gx.div_euclid(TILE_SIZE as i64);
        let ty = gy.div_euclid(TILE_SIZE as i64);
        let px = gx.rem_euclid(TILE_SIZE as i64) as usize;
        let py = gy.rem_euclid(TILE_SIZE as i64) as usize;
        (tx, ty, px, py)
    }

    /// Latitude band of a tile row: `(top, bottom)`, top is the northern edge.
    pub fn row_band(&self, ty: i64) -> (f64, f64) {
        let top = self.origin_lat - (ty as f64) * (TILE_SIZE as f64) * self.step_lat;
        let bottom = top - (TILE_SIZE as f64) * self.step_lat;
        (top, bottom)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const STEP5: f64 = 1.0 / 18000.0;

    #[test]
    fn origin_covers_data_on_grid() {
        // mesh 51346200 bounds
        let g =
            TileGrid::new(0.0, 0.0, STEP5, STEP5).from_bounds(34.5, 134.25, 34.508333333, 134.2625);
        // top aligned just above max_lat, left at min_lon
        assert!((g.origin_lat - 34.508333333).abs() < STEP5);
        assert!((g.origin_lon - 134.25).abs() < 1e-12);
    }

    #[test]
    fn cell_centers_map_to_expected_global_cells() {
        let g =
            TileGrid::new(0.0, 0.0, STEP5, STEP5).from_bounds(34.5, 134.25, 34.508333333, 134.2625);
        // cell (0,0) center -> global (0,0); cell (149,224) -> (224,149)
        let (lat, lon) = (34.508333333 - 0.5 * STEP5, 134.25 + 0.5 * STEP5);
        assert_eq!(g.global_cell(lat, lon), (0, 0));
        let (lat, lon) = (34.508333333 - 149.5 * STEP5, 134.25 + 224.5 * STEP5);
        assert_eq!(g.global_cell(lat, lon), (224, 149));
    }

    #[test]
    fn tile_decomposition() {
        let g = TileGrid::new(0.0, 0.0, STEP5, STEP5);
        assert_eq!(g.tile_of(255, 255), (0, 0, 255, 255));
        assert_eq!(g.tile_of(256, 256), (1, 1, 0, 0));
        assert_eq!(g.tile_of(300, 500), (1, 1, 44, 244));
    }
}
