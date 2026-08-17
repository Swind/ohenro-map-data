/// Grid coordinate model for a normalized GSI DEM raster.
///
/// Uses the geographic (lat/lon) coordinate system defined by the GML
/// Envelope. The grid's low corner maps to the envelope lowerCorner
/// (south-west), high corner to upperCorner (north-east). Conversion to
/// Web Mercator is deliberately deferred (plan §12).
use crate::gsi::model::{GsiDemRaster, SampleKind};

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct GridBounds {
    pub min_lat: f64,
    pub min_lon: f64,
    pub max_lat: f64,
    pub max_lon: f64,
}

impl GridBounds {
    pub fn from_raster(r: &GsiDemRaster) -> GridBounds {
        GridBounds {
            min_lat: r.lower_lat,
            min_lon: r.lower_lon,
            max_lat: r.upper_lat,
            max_lon: r.upper_lon,
        }
    }

    pub fn lat_step(&self, height: usize) -> f64 {
        (self.max_lat - self.min_lat) / height as f64
    }

    pub fn lon_step(&self, width: usize) -> f64 {
        (self.max_lon - self.min_lon) / width as f64
    }

    pub fn contains(&self, lat: f64, lon: f64) -> bool {
        lat >= self.min_lat && lat <= self.max_lat && lon >= self.min_lon && lon <= self.max_lon
    }
}

/// Maps a tuple index to a grid (row, col) using the traversal rule
/// defined by the XML (`sequenceRule` order + `startPoint`).
///
/// GML semantics (Phase 2): the GML grid is defined with `low` at the
/// envelope SW corner and `high` at NE (y north-positive), but GSI stores
/// raster rows north-up (row 0 = upperCorner latitude). After applying the
/// row flip, the `+x-y` sequenceRule (x east, then y south) becomes:
/// rows are stored from `start_y` southward to the bottom edge; the first
/// row is partial (columns `start_x .. high_x`), and after reaching the
/// east edge, x wraps to column 0 for subsequent rows.
///
/// Verified: sample-count formula `(W-sx) + W*(H-1-sy)` holds for all 69
/// DEM5A meshes, and DEM5 vs DEM10B cross-validation confirms the
/// resulting coordinate mapping (see `gsi-dem validate`).
pub fn tuple_index_to_grid(r: &GsiDemRaster, index: usize) -> Option<(usize, usize)> {
    let width = r.width();
    let sx = r.start_x as usize;
    let sy = r.start_y as usize;

    let first_row_count = width.saturating_sub(sx);
    if index < first_row_count {
        return Some((sy, sx + index));
    }
    let rest = index - first_row_count;
    let row = sy + 1 + rest / width;
    let col = rest % width;
    if row >= r.height() {
        return None;
    }
    Some((row, col))
}

/// Inverse: grid (row, col) -> tuple index, if that cell is stored.
pub fn grid_to_tuple_index(r: &GsiDemRaster, row: usize, col: usize) -> Option<usize> {
    let width = r.width();
    let sx = r.start_x as usize;
    let sy = r.start_y as usize;

    if row < sy || row >= r.height() {
        return None;
    }
    if row == sy {
        if col < sx {
            return None;
        }
        return Some(col - sx);
    }
    let rest = (row - sy - 1) * width + col;
    Some((width - sx) + rest)
}

/// Grid cell center coordinate. Sample (row=0,col=0) is the NW-most cell:
/// GSI DEM grids store row 0 at the north edge (upperCorner latitude),
/// increasing southward. Verified against known Shodoshima landmarks.
pub fn cell_center(r: &GsiDemRaster, row: usize, col: usize) -> (f64, f64) {
    let b = GridBounds::from_raster(r);
    let lat_step = b.lat_step(r.height());
    let lon_step = b.lon_step(r.width());
    let lat = b.max_lat - (row as f64 + 0.5) * lat_step;
    let lon = b.min_lon + (col as f64 + 0.5) * lon_step;
    (lat, lon)
}

/// Nearest grid cell (row, col) for a lat/lon inside the bounds.
pub fn nearest_cell(r: &GsiDemRaster, lat: f64, lon: f64) -> Option<(usize, usize)> {
    let b = GridBounds::from_raster(r);
    if !b.contains(lat, lon) {
        return None;
    }
    let lat_step = b.lat_step(r.height());
    let lon_step = b.lon_step(r.width());
    let row = ((b.max_lat - lat) / lat_step).floor() as usize;
    let col = ((lon - b.min_lon) / lon_step).floor() as usize;
    let row = row.min(r.height() - 1);
    let col = col.min(r.width() - 1);
    Some((row, col))
}

pub struct ElevationSample {
    pub meters: Option<f32>,
    pub kind: SampleKind,
}

/// Fetch the sample stored for a grid cell (row, col).
pub fn sample_at(r: &GsiDemRaster, row: usize, col: usize) -> Option<ElevationSample> {
    let idx = grid_to_tuple_index(r, row, col)?;
    let elevation = r.elevation.get(idx)?;
    let mask = r.mask.get(idx)?;
    let kind = match *mask {
        1 => SampleKind::Terrain,
        2 => SampleKind::Sea,
        3 => SampleKind::InlandWater,
        _ => SampleKind::NoData,
    };
    Some(ElevationSample {
        meters: if elevation.is_nan() { None } else { Some(*elevation) },
        kind,
    })
}