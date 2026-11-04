//! Per-mesh DEM5 merge: DEM5A > DEM5B > DEM5C at pixel level (plan §15).
//!
//! Each mesh may be covered by up to three rasters (one per source). The
//! merge produces a full W×H grid where every cell records the
//! highest-priority source that has a valid (non-NoData) sample. "Valid"
//! includes Sea and InlandWater — only NoData loses to a lower-priority
//! source.
//!
//! The output keeps a per-cell source code (plan §16): 0=NODATA,
//! 1=DEM10B, 2=DEM5C, 3=DEM5B, 4=DEM5A. DEM10B is Phase 4 and never
//! participates here, but the codes leave room for it.

use crate::gsi::error::{DemError, DemResult};
use crate::gsi::model::{DemSource, GsiDemRaster, SampleKind};
use crate::raster::grid::{GridBounds, grid_to_tuple_index};
use std::io::{BufReader, BufWriter, Read, Write};
use std::path::Path;

pub const SOURCE_NODATA: u8 = 0;
pub const SOURCE_DEM10B: u8 = 1;
pub const SOURCE_DEM5C: u8 = 2;
pub const SOURCE_DEM5B: u8 = 3;
pub const SOURCE_DEM5A: u8 = 4;

/// Binary on-disk format for a merged mesh (`write_bin` / `read_bin`):
/// magic `GM5M`, version u32, mesh_len u16, mesh bytes, 4×f64 bounds,
/// u32 width, u32 height, then f32 elevation, u8 mask, u8 source
/// (each W×H, row-major north->south).
const BIN_MAGIC: &[u8; 4] = b"GM5M";
const BIN_VERSION: u32 = 1;

/// A merged, full-coverage per-mesh raster. Row 0 is the north edge
/// (max_lat), consistent with the source rasters.
#[derive(Debug, Clone)]
pub struct MergedMesh {
    pub mesh: String,
    pub bounds: GridBounds,
    pub width: usize,
    pub height: usize,
    /// Full grid, row-major north->south; NaN where no source has a value.
    pub elevation: Vec<f32>,
    /// Full grid, `SampleKind` as u8.
    pub mask: Vec<u8>,
    /// Full grid, plan §16 source codes (`SOURCE_*`).
    pub source: Vec<u8>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct MergedSample {
    pub meters: Option<f32>,
    pub kind: SampleKind,
    pub source_code: u8,
}

impl MergedMesh {
    pub fn grid_capacity(&self) -> usize {
        self.width * self.height
    }

    pub fn kind_counts(&self) -> [(SampleKind, usize); 6] {
        let mut counts = [0usize; 6];
        for &m in &self.mask {
            counts[m as usize] += 1;
        }
        [
            (SampleKind::NoData, counts[0]),
            (SampleKind::Terrain, counts[1]),
            (SampleKind::Sea, counts[2]),
            (SampleKind::InlandWater, counts[3]),
            (SampleKind::Seabed, counts[4]),
            (SampleKind::InlandBottom, counts[5]),
        ]
    }

    /// Number of grid cells won by each source (plan §16 code).
    pub fn source_counts(&self) -> [usize; 5] {
        let mut counts = [0usize; 5];
        for &s in &self.source {
            counts[s as usize] += 1;
        }
        counts
    }

    /// Grid cell center coordinate (north-up, same model as `cell_center`).
    pub fn cell_center(&self, row: usize, col: usize) -> (f64, f64) {
        let lat_step = self.bounds.lat_step(self.height);
        let lon_step = self.bounds.lon_step(self.width);
        let lat = self.bounds.max_lat - (row as f64 + 0.5) * lat_step;
        let lon = self.bounds.min_lon + (col as f64 + 0.5) * lon_step;
        (lat, lon)
    }

    /// Nearest grid cell for a lat/lon inside the bounds.
    pub fn nearest_cell(&self, lat: f64, lon: f64) -> Option<(usize, usize)> {
        if !self.bounds.contains(lat, lon) {
            return None;
        }
        let lat_step = self.bounds.lat_step(self.height);
        let lon_step = self.bounds.lon_step(self.width);
        let row = ((self.bounds.max_lat - lat) / lat_step).floor() as usize;
        let col = ((lon - self.bounds.min_lon) / lon_step).floor() as usize;
        Some((row.min(self.height - 1), col.min(self.width - 1)))
    }

    /// Sample at a grid cell.
    pub fn sample_at(&self, row: usize, col: usize) -> Option<MergedSample> {
        let i = row * self.width + col;
        let elevation = *self.elevation.get(i)?;
        let mask = *self.mask.get(i)?;
        let code = *self.source.get(i)?;
        let kind = match mask {
            1 => SampleKind::Terrain,
            2 => SampleKind::Sea,
            3 => SampleKind::InlandWater,
            4 => SampleKind::Seabed,
            5 => SampleKind::InlandBottom,
            _ => SampleKind::NoData,
        };
        Some(MergedSample {
            meters: if elevation.is_nan() {
                None
            } else {
                Some(elevation)
            },
            kind,
            source_code: code,
        })
    }
}

/// Merge the rasters of one mesh with DEM5A > DEM5B > DEM5C priority.
///
/// All rasters must describe the same grid geometry (same bounds and
/// dimensions); otherwise the caller made a grouping error.
pub fn merge_rasters(mesh: &str, rasters: &[(&DemSource, &GsiDemRaster)]) -> DemResult<MergedMesh> {
    if rasters.is_empty() {
        return Err(DemError::Parse {
            context: format!("merge: mesh {mesh} has no rasters"),
        });
    }

    let first = rasters[0].1;
    let w = first.width();
    let h = first.height();
    for (src, r) in &rasters[1..] {
        let ok = r.width() == w
            && r.height() == h
            && (r.lower_lat - first.lower_lat).abs() < 1e-9
            && (r.lower_lon - first.lower_lon).abs() < 1e-9
            && (r.upper_lat - first.upper_lat).abs() < 1e-9
            && (r.upper_lon - first.upper_lon).abs() < 1e-9;
        if !ok {
            return Err(DemError::Unsupported {
                context: format!(
                    "merge: mesh {mesh}: {} and {} have conflicting grid geometry",
                    first.source, src
                ),
            });
        }
    }

    // highest priority first
    let mut order: Vec<&(&DemSource, &GsiDemRaster)> = rasters.iter().collect();
    order.sort_by(|a, b| b.0.source_code().cmp(&a.0.source_code()));

    let n = w * h;
    let mut elevation = vec![f32::NAN; n];
    let mut mask = vec![SampleKind::NoData as u8; n];
    let mut source = vec![SOURCE_NODATA; n];

    for row in 0..h {
        for col in 0..w {
            for (src, r) in &order {
                let Some(idx) = grid_to_tuple_index(r, row, col) else {
                    continue;
                };
                // Partial meshes may end on a partial row (e.g. stored
                // 5039 of 33750 with start=(13,0)): cells past the stored
                // region map to an index beyond sample_count. Those cells
                // have no sample from this source.
                if idx >= r.sample_count() {
                    continue;
                }
                if r.mask[idx] == SampleKind::NoData as u8 {
                    continue;
                }
                let cell = row * w + col;
                elevation[cell] = r.elevation[idx];
                mask[cell] = r.mask[idx];
                source[cell] = src.source_code();
                break;
            }
        }
    }

    Ok(MergedMesh {
        mesh: mesh.to_string(),
        bounds: GridBounds::from_raster(first),
        width: w,
        height: h,
        elevation,
        mask,
        source,
    })
}

/// Header of a `GM5M` merged mesh binary (bounds + grid size, no samples).
#[derive(Debug, Clone)]
pub struct MergedMeshHeader {
    pub mesh: String,
    pub bounds: GridBounds,
    pub width: usize,
    pub height: usize,
}

impl MergedMesh {
    /// Read only the header of a `GM5M` file (cheap for sweeps over many files).
    pub fn read_bin_header(path: &Path) -> DemResult<MergedMeshHeader> {
        let file = std::fs::File::open(path).map_err(|e| DemError::Io {
            context: format!("open {}", path.display()),
            source: e,
        })?;
        let mut r = BufReader::new(file);

        let mut magic = [0u8; 4];
        r.read_exact(&mut magic).map_err(io_err(path))?;
        if &magic != BIN_MAGIC {
            return Err(DemError::Parse {
                context: format!("{}: not a GM5M merged mesh", path.display()),
            });
        }
        let version = read_u32(&mut r, path)?;
        if version != BIN_VERSION {
            return Err(DemError::Unsupported {
                context: format!("{}: GM5M version {version} unsupported", path.display()),
            });
        }
        let mesh_len = read_u16(&mut r, path)? as usize;
        let mut mesh = vec![0u8; mesh_len];
        r.read_exact(&mut mesh).map_err(io_err(path))?;
        let mesh = String::from_utf8_lossy(&mesh).into_owned();
        let min_lat = read_f64(&mut r, path)?;
        let min_lon = read_f64(&mut r, path)?;
        let max_lat = read_f64(&mut r, path)?;
        let max_lon = read_f64(&mut r, path)?;
        let width = read_u32(&mut r, path)? as usize;
        let height = read_u32(&mut r, path)? as usize;
        Ok(MergedMeshHeader {
            mesh,
            bounds: GridBounds {
                min_lat,
                min_lon,
                max_lat,
                max_lon,
            },
            width,
            height,
        })
    }

    /// Serialize to the `GM5M` binary format (Phase 3 `--out-dir` artifact).
    pub fn write_bin(&self, path: &Path) -> DemResult<()> {
        let mut w = BufWriter::new(std::fs::File::create(path).map_err(|e| DemError::Io {
            context: format!("create {}", path.display()),
            source: e,
        })?);
        w.write_all(BIN_MAGIC).map_err(io_err(path))?;
        w.write_all(&BIN_VERSION.to_le_bytes())
            .map_err(io_err(path))?;
        w.write_all(&(self.mesh.len() as u16).to_le_bytes())
            .map_err(io_err(path))?;
        w.write_all(self.mesh.as_bytes()).map_err(io_err(path))?;
        w.write_all(&self.bounds.min_lat.to_le_bytes())
            .map_err(io_err(path))?;
        w.write_all(&self.bounds.min_lon.to_le_bytes())
            .map_err(io_err(path))?;
        w.write_all(&self.bounds.max_lat.to_le_bytes())
            .map_err(io_err(path))?;
        w.write_all(&self.bounds.max_lon.to_le_bytes())
            .map_err(io_err(path))?;
        w.write_all(&(self.width as u32).to_le_bytes())
            .map_err(io_err(path))?;
        w.write_all(&(self.height as u32).to_le_bytes())
            .map_err(io_err(path))?;
        for v in &self.elevation {
            w.write_all(&v.to_le_bytes()).map_err(io_err(path))?;
        }
        w.write_all(&self.mask).map_err(io_err(path))?;
        w.write_all(&self.source).map_err(io_err(path))?;
        w.flush().map_err(io_err(path))?;
        Ok(())
    }

    /// Deserialize a `GM5M` merged mesh binary.
    pub fn read_bin(path: &Path) -> DemResult<MergedMesh> {
        let file = std::fs::File::open(path).map_err(|e| DemError::Io {
            context: format!("open {}", path.display()),
            source: e,
        })?;
        let mut r = BufReader::new(file);

        let mut magic = [0u8; 4];
        r.read_exact(&mut magic).map_err(io_err(path))?;
        if &magic != BIN_MAGIC {
            return Err(DemError::Parse {
                context: format!("{}: not a GM5M merged mesh", path.display()),
            });
        }
        let version = read_u32(&mut r, path)?;
        if version != BIN_VERSION {
            return Err(DemError::Unsupported {
                context: format!("{}: GM5M version {version} unsupported", path.display()),
            });
        }
        let mesh_len = read_u16(&mut r, path)? as usize;
        let mut mesh = vec![0u8; mesh_len];
        r.read_exact(&mut mesh).map_err(io_err(path))?;
        let mesh = String::from_utf8_lossy(&mesh).into_owned();

        let min_lat = read_f64(&mut r, path)?;
        let min_lon = read_f64(&mut r, path)?;
        let max_lat = read_f64(&mut r, path)?;
        let max_lon = read_f64(&mut r, path)?;
        let width = read_u32(&mut r, path)? as usize;
        let height = read_u32(&mut r, path)? as usize;

        let n = width * height;
        let mut elevation = vec![0.0f32; n];
        for v in elevation.iter_mut() {
            *v = read_f32(&mut r, path)?;
        }
        let mut mask = vec![0u8; n];
        r.read_exact(&mut mask).map_err(io_err(path))?;
        let mut source = vec![0u8; n];
        r.read_exact(&mut source).map_err(io_err(path))?;

        Ok(MergedMesh {
            mesh,
            bounds: GridBounds {
                min_lat,
                min_lon,
                max_lat,
                max_lon,
            },
            width,
            height,
            elevation,
            mask,
            source,
        })
    }
}

fn io_err(path: &Path) -> impl FnOnce(std::io::Error) -> DemError {
    move |e| DemError::Io {
        context: format!("read/write {}", path.display()),
        source: e,
    }
}

fn read_u16<R: Read>(r: &mut R, path: &Path) -> DemResult<u16> {
    let mut b = [0u8; 2];
    r.read_exact(&mut b).map_err(io_err(path))?;
    Ok(u16::from_le_bytes(b))
}

fn read_u32<R: Read>(r: &mut R, path: &Path) -> DemResult<u32> {
    let mut b = [0u8; 4];
    r.read_exact(&mut b).map_err(io_err(path))?;
    Ok(u32::from_le_bytes(b))
}

fn read_f32<R: Read>(r: &mut R, path: &Path) -> DemResult<f32> {
    let mut b = [0u8; 4];
    r.read_exact(&mut b).map_err(io_err(path))?;
    Ok(f32::from_le_bytes(b))
}

fn read_f64<R: Read>(r: &mut R, path: &Path) -> DemResult<f64> {
    let mut b = [0u8; 8];
    r.read_exact(&mut b).map_err(io_err(path))?;
    Ok(f64::from_le_bytes(b))
}
