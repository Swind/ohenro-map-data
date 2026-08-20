//! `export-vrt`: export one layer of the elevation SQLite as a raw Int16
//! raster + GDAL VRT (plan §45, docs/elevation_visualization_pipeline.md §6).
//!
//! The exporter writes a header-less row-major signed-Int16-little-endian
//! raster and a `VRTRawRasterBand` VRT that describes it. GeoTIFF conversion
//! is intentionally left to the GDAL CLI so `gsi-dem` never links libgdal.

use std::path::PathBuf;

use clap::Args;

use crate::db::{ElevationDb, LAYER_DEM5, LAYER_DEM10};
use crate::raster::vrt::{RawWriter, write_vrt};
use crate::tile::grid::TILE_SIZE;

/// Default GDAL SRS for the GSI source CRS (JGD2024 geographic 2D).
///
/// GSI GML declares `srsName="fguuid:jgd2024.bl"`. In the EPSG registry this
/// is EPSG:6668 (GRS80 geographic 2D). GDAL 3.6.3 labels it "JGD2011" because
/// its bundled registry predates the JGD2024 rename, but it is the correct
/// datum for the source data. Lat/lon on this CRS vs WGS84 differ by <1m,
/// which is negligible for 20m contours / 12m terrain. Allowed to override.
pub const DEFAULT_SRS: &str = "EPSG:6668";

/// Export a DEM layer from the SQLite database as raw + VRT.
#[derive(Debug, Args)]
pub struct ExportVrtArgs {
    /// Path to the SQLite elevation database.
    pub database: PathBuf,

    /// Layer to export: 5 (DEM5) or 10 (DEM10).
    #[arg(long, value_parser = clap::value_parser!(i64))]
    pub layer: i64,

    /// Output `.vrt` path; the sibling `.raw` raster is written alongside.
    #[arg(long)]
    pub output: PathBuf,

    /// GDAL SRS/WKT for the exported raster.
    #[arg(long, default_value = DEFAULT_SRS)]
    pub srs: String,

    /// Overwrite an existing `.vrt` / `.raw` pair.
    #[arg(long)]
    pub force: bool,
}

fn fail(context: String) -> anyhow::Error {
    anyhow::anyhow!(context)
}

pub fn run(args: &ExportVrtArgs) -> anyhow::Result<()> {
    // --- CLI validation (spec §6.2) ---
    if !args.database.exists() {
        return Err(fail(format!(
            "database not found: {}",
            args.database.display()
        )));
    }
    if args.layer != LAYER_DEM5 && args.layer != LAYER_DEM10 {
        return Err(fail(format!(
            "--layer must be 5 or 10 (got {})",
            args.layer
        )));
    }
    if args
        .output
        .extension()
        .and_then(|e| e.to_str())
        .map(|e| e != "vrt")
        .unwrap_or(true)
    {
        return Err(fail(format!(
            "--output must end in .vrt (got {})",
            args.output.display()
        )));
    }

    let db = ElevationDb::open(&args.database)?;
    validate_metadata(&db)?;

    let layer_name = if args.layer == LAYER_DEM10 {
        "dem10"
    } else {
        "dem5"
    };
    let grid = db
        .grid(args.layer)?
        .ok_or_else(|| fail(format!("{layer_name} grid metadata missing in database")))?;
    let extent = db
        .tile_extent(args.layer)?
        .ok_or_else(|| fail(format!("{layer_name} has no elevation tiles")))?;
    if grid.tile_size != TILE_SIZE {
        return Err(fail(format!(
            "metadata tile_size {} != compiled {}",
            grid.tile_size, TILE_SIZE
        )));
    }

    let width = (extent.max_tile_x - extent.min_tile_x + 1)
        .checked_mul(TILE_SIZE as i64)
        .ok_or_else(|| fail("width overflow".to_string()))? as usize;
    let height = (extent.max_tile_y - extent.min_tile_y + 1)
        .checked_mul(TILE_SIZE as i64)
        .ok_or_else(|| fail("height overflow".to_string()))? as usize;
    let west = grid.origin_lon + (extent.min_tile_x as f64) * (TILE_SIZE as f64) * grid.step_lon;
    let north = grid.origin_lat - (extent.min_tile_y as f64) * (TILE_SIZE as f64) * grid.step_lat;
    let geo_transform = [west, grid.step_lon, 0.0, north, 0.0, -grid.step_lat];

    // raw path = sibling of the .vrt with .raw extension
    let raw_path = args.output.with_extension("raw");

    // --- overwrite guard (spec §6.2) ---
    for p in [&args.output, &raw_path] {
        if p.exists() && !args.force {
            return Err(fail(format!(
                "{} already exists; pass --force to overwrite",
                p.display()
            )));
        }
    }
    if let Some(parent) = args.output.parent() {
        std::fs::create_dir_all(parent)
            .map_err(|e| anyhow::anyhow!("create {}: {e}", parent.display()))?;
    }

    let raw_filename = raw_path
        .file_name()
        .and_then(|n| n.to_str())
        .ok_or_else(|| fail("invalid raw filename".to_string()))?;

    // --- write raw (spec §6.5) ---
    println!(
        "==> exporting layer {layer_name} ({width}x{height}) -> {} + {}",
        raw_path.display(),
        args.output.display()
    );
    let mut raw = RawWriter::create(&raw_path, width, height, TILE_SIZE)?;
    let mut written = 0u64;
    for ty in extent.min_tile_y..=extent.max_tile_y {
        for tx in extent.min_tile_x..=extent.max_tile_x {
            if let Some(cells) = db.read_elevation_tile(args.layer, tx, ty)? {
                raw.write_tile(tx, ty, &cells)?;
                written += 1;
            }
        }
    }
    raw.finish()?;

    write_vrt(
        &args.output,
        width,
        height,
        &args.srs,
        geo_transform,
        raw_filename,
    )?;

    println!(
        "wrote {} tiles to {} ({:.1} MB raw)",
        written,
        raw_path.display(),
        std::fs::metadata(&raw_path)
            .map(|m| m.len() as f64 / 1e6)
            .unwrap_or(0.0)
    );
    Ok(())
}

/// Validate DB metadata the exporter depends on (spec §6.2).
fn validate_metadata(db: &ElevationDb) -> anyhow::Result<()> {
    let compression = db.metadata("compression")?.unwrap_or_default();
    if compression != "zstd" {
        return Err(fail(format!(
            "metadata compression must be 'zstd' (got {compression:?})"
        )));
    }
    let encoding = db.metadata("encoding")?.unwrap_or_default();
    if encoding != "int16_meters" {
        return Err(fail(format!(
            "metadata encoding must be 'int16_meters' (got {encoding:?})"
        )));
    }
    Ok(())
}
