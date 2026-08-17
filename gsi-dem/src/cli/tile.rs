use std::collections::HashMap;
use std::io::BufWriter;
use std::path::{Path, PathBuf};

use clap::Args;
use serde::Serialize;

use crate::gsi::archive;
use crate::gsi::model::DemSource;
use crate::gsi::xml::parse_dem;
use crate::raster::merged::MergedMesh;
use crate::tile::codec::{compress, dequantize};
use crate::tile::grid::{TILE_SIZE, TileGrid};
use crate::tile::rasterize::{TileAcc, place_dem10, place_mesh};
use crate::tile::tilefile::{LAYER_DEM5, LAYER_DEM10, TileFile};

/// Grid resolution per layer (degrees per cell).
const STEP_DEM5: f64 = 1.0 / 18000.0;
const STEP_DEM10: f64 = 1.0 / 9000.0;

/// Re-cut merged rasters into a fixed 256×256 geographic tile grid.
///
/// Consumes the per-mesh merged rasters produced by `merge --out-dir`
/// (plan §4 work/merged) and the DEM10B layer, and writes zstd-compressed
/// int16 elevation tiles + u8 source tiles (plan §18-§22). The same tile
/// grid is what Phase 6 loads into SQLite.
#[derive(Debug, Args)]
pub struct TileArgs {
    /// Directory of merged per-mesh .bin files (from `merge --out-dir`).
    #[arg(long)]
    pub merged: PathBuf,

    /// DEM10B source directory (one archive per region).
    #[arg(long, default_value = "source/GSI/DEM10B")]
    pub dem10b: PathBuf,

    /// Output directory; tiles land in `<out>/dem5/` and `<out>/dem10/`.
    #[arg(long)]
    pub out: PathBuf,

    /// Write a JSON report here.
    #[arg(long)]
    pub report: Option<PathBuf>,

    /// Print DEM5 + DEM10 fallback elevation at this point, read back from
    /// the written tiles (round-trip verification).
    #[arg(long)]
    pub check_lat: Option<f64>,

    /// Print DEM5 + DEM10 fallback elevation at this point (with --check-lat).
    #[arg(long)]
    pub check_lon: Option<f64>,
}

#[derive(Debug, Clone, Copy, Default, Serialize)]
struct LayerStats {
    tiles: usize,
    cells_valid: u64,
    cells_nodata: u64,
    bytes_raw: u64,
    bytes_zstd: u64,
}

#[derive(Debug, Serialize, Default)]
struct Report {
    grid_dem5: GridInfo,
    grid_dem10: GridInfo,
    dem5: LayerStats,
    dem10: LayerStats,
}

#[derive(Debug, Serialize, Default)]
struct GridInfo {
    origin_lat: f64,
    origin_lon: f64,
    step_lat: f64,
    step_lon: f64,
    tile_size: usize,
}

pub fn run(args: &TileArgs) -> anyhow::Result<()> {
    // ---- scan merged bins + headers ----
    let mut headers: Vec<(PathBuf, crate::raster::merged::MergedMeshHeader)> = Vec::new();
    for entry in std::fs::read_dir(&args.merged)? {
        let entry = entry?;
        let p = entry.path();
        if p.extension().is_some_and(|e| e == "bin") {
            headers.push((p.clone(), MergedMesh::read_bin_header(&p)?));
        }
    }
    if headers.is_empty() {
        anyhow::bail!("no *.bin merged meshes found in {}", args.merged.display());
    }
    headers.sort_by(|a, b| a.1.mesh.cmp(&b.1.mesh));

    let (mut min_lat, mut min_lon, mut max_lat, mut max_lon) = (
        f64::INFINITY,
        f64::INFINITY,
        f64::NEG_INFINITY,
        f64::NEG_INFINITY,
    );
    for (_, h) in &headers {
        min_lat = min_lat.min(h.bounds.min_lat);
        min_lon = min_lon.min(h.bounds.min_lon);
        max_lat = max_lat.max(h.bounds.max_lat);
        max_lon = max_lon.max(h.bounds.max_lon);
    }
    println!(
        "dataset bounds: {min_lat:.6} {min_lon:.6} -> {max_lat:.6} {max_lon:.6} ({} merged meshes)",
        headers.len()
    );

    std::fs::create_dir_all(&args.out)?;
    let mut report = Report::default();

    // ---- DEM5 layer ----
    let grid5 = TileGrid::new(0.0, 0.0, STEP_DEM5, STEP_DEM5)
        .from_bounds(min_lat, min_lon, max_lat, max_lon);
    report.grid_dem5 = grid_info(grid5);
    let (max_gx5, max_gy5) = grid5.cell_extent(min_lat, min_lon, max_lat, max_lon);
    let max_ty5 = max_gy5 / (TILE_SIZE as i64);
    let out5 = args.out.join("dem5");
    std::fs::create_dir_all(&out5)?;
    println!(
        "DEM5 grid: origin=({:.6},{:.6}) step={:.3e} tiles={}x{}",
        grid5.origin_lat,
        grid5.origin_lon,
        STEP_DEM5,
        max_gx5 / (TILE_SIZE as i64) + 1,
        max_ty5 + 1
    );
    for ty in 0..=max_ty5 {
        let (row_top, row_bot) = grid5.row_band(ty);
        let mut tiles: HashMap<i64, TileAcc> = HashMap::new();
        for (path, h) in &headers {
            if h.bounds.max_lat < row_bot || h.bounds.min_lat > row_top {
                continue;
            }
            let mesh = MergedMesh::read_bin(path)?;
            place_mesh(&mesh, &grid5, ty, &mut tiles);
        }
        write_row(&out5, LAYER_DEM5, ty, &mut tiles, &mut report.dem5)?;
    }

    // ---- DEM10 layer ----
    let mut regions: Vec<(PathBuf, crate::raster::grid::GridBounds)> = Vec::new();
    collect_dem10_regions(&args.dem10b, &mut regions)?;
    if !regions.is_empty() {
        let grid10 = TileGrid::new(0.0, 0.0, STEP_DEM10, STEP_DEM10)
            .from_bounds(min_lat, min_lon, max_lat, max_lon);
        report.grid_dem10 = grid_info(grid10);
        let (_, max_gy10) = grid10.cell_extent(min_lat, min_lon, max_lat, max_lon);
        let max_ty10 = max_gy10 / (TILE_SIZE as i64);
        let out10 = args.out.join("dem10");
        std::fs::create_dir_all(&out10)?;
        regions.sort_by(|a, b| b.1.max_lat.partial_cmp(&a.1.max_lat).unwrap());

        let mut active: Vec<(
            crate::raster::grid::GridBounds,
            crate::gsi::model::GsiDemRaster,
        )> = Vec::new();
        let mut idx = 0usize;
        for ty in 0..=max_ty10 {
            let (row_top, row_bot) = grid10.row_band(ty);
            while idx < regions.len() && regions[idx].1.max_lat > row_bot {
                let (path, b) = &regions[idx];
                let raster = load_region_raster(path)?;
                active.push((*b, raster));
                idx += 1;
            }
            active.retain(|(b, _)| b.min_lat <= row_top);
            let mut tiles: HashMap<i64, TileAcc> = HashMap::new();
            for (_, r) in &active {
                place_dem10(r, &grid10, ty, &mut tiles);
            }
            write_row(&out10, LAYER_DEM10, ty, &mut tiles, &mut report.dem10)?;
        }
    } else {
        println!(
            "WARN: no DEM10B archives found under {}",
            args.dem10b.display()
        );
    }

    print_stats("DEM5", &report.dem5);
    print_stats("DEM10", &report.dem10);

    if let (Some(lat), Some(lon)) = (args.check_lat, args.check_lon) {
        check_point(&args.out, &grid5, &report.grid_dem10, lat, lon)?;
    }

    if let Some(path) = &args.report {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        serde_json::to_writer_pretty(BufWriter::new(std::fs::File::create(path)?), &report)?;
        println!("report written to {}", path.display());
    }
    Ok(())
}

fn grid_info(g: TileGrid) -> GridInfo {
    GridInfo {
        origin_lat: g.origin_lat,
        origin_lon: g.origin_lon,
        step_lat: g.step_lat,
        step_lon: g.step_lon,
        tile_size: TILE_SIZE,
    }
}

fn write_row(
    out: &Path,
    layer: u8,
    ty: i64,
    tiles: &mut HashMap<i64, TileAcc>,
    stats: &mut LayerStats,
) -> anyhow::Result<()> {
    let mut txs: Vec<i64> = tiles.keys().copied().collect();
    txs.sort_unstable();
    for tx in txs {
        let acc = tiles.remove(&tx).unwrap();
        if acc.cells == 0 {
            continue;
        }
        let mut elev_bytes = Vec::with_capacity(TILE_SIZE * TILE_SIZE * 2);
        for v in acc.elevation.iter() {
            elev_bytes.extend_from_slice(&v.to_le_bytes());
        }
        let zstd = compress(&elev_bytes)?;
        let tf = TileFile {
            layer,
            tile_x: tx as u32,
            tile_y: ty as u32,
            elevation_zstd: zstd,
            source: acc.source.to_vec(),
        };
        let path = out.join(format!("{ty:06}_{tx:06}.tile"));
        tf.write(&path)?;
        stats.tiles += 1;
        stats.cells_valid += acc.cells as u64;
        stats.cells_nodata += (TILE_SIZE * TILE_SIZE - acc.cells) as u64;
        stats.bytes_raw += (TILE_SIZE * TILE_SIZE * 2) as u64;
        stats.bytes_zstd += (tf.elevation_zstd.len() + tf.source.len()) as u64;
    }
    Ok(())
}

fn print_stats(name: &str, s: &LayerStats) {
    println!(
        "{name}: {} tiles, {} valid / {} nodata cells, zstd {:.1} MB / raw {:.1} MB (ratio {:.2})",
        s.tiles,
        s.cells_valid,
        s.cells_nodata,
        s.bytes_zstd as f64 / 1e6,
        s.bytes_raw as f64 / 1e6,
        if s.bytes_raw > 0 {
            s.bytes_raw as f64 / s.bytes_zstd.max(1) as f64
        } else {
            0.0
        }
    );
}

/// Read a merged mesh's header from a directory of `.bin` files.
fn collect_dem10_regions(
    dir: &Path,
    out: &mut Vec<(PathBuf, crate::raster::grid::GridBounds)>,
) -> anyhow::Result<()> {
    let mut stack = vec![dir.to_path_buf()];
    while let Some(d) = stack.pop() {
        for entry in std::fs::read_dir(&d)? {
            let entry = entry?;
            let p = entry.path();
            if p.is_dir() {
                stack.push(p);
            } else if p.extension().is_some_and(|e| e == "zip") {
                let fname = p
                    .file_name()
                    .unwrap_or_default()
                    .to_string_lossy()
                    .into_owned();
                if DemSource::from_entry_name(&fname) != Some(DemSource::Dem10B) {
                    continue;
                }
                let meta = load_region_meta(&p)?;
                out.push((
                    p,
                    crate::raster::grid::GridBounds {
                        min_lat: meta.lower_lat,
                        min_lon: meta.lower_lon,
                        max_lat: meta.upper_lat,
                        max_lon: meta.upper_lon,
                    },
                ));
            }
        }
    }
    Ok(())
}

fn load_region_meta(path: &Path) -> anyhow::Result<crate::gsi::xml::GsiDemMeta> {
    let mut zip = archive::open_archive(path)?;
    let names = archive::xml_entry_names(&mut zip)?;
    let name = names
        .first()
        .ok_or_else(|| anyhow::anyhow!("{}: no XML entries", path.display()))?;
    let reader = archive::read_entry(&mut zip, name)?;
    Ok(crate::gsi::xml::parse_dem_meta(name, reader)?)
}

fn load_region_raster(path: &Path) -> anyhow::Result<crate::gsi::model::GsiDemRaster> {
    let mut zip = archive::open_archive(path)?;
    let names = archive::xml_entry_names(&mut zip)?;
    let name = names
        .first()
        .ok_or_else(|| anyhow::anyhow!("{}: no XML entries", path.display()))?;
    let reader = archive::read_entry(&mut zip, name)?;
    Ok(parse_dem(name, reader)?)
}

/// Round-trip check: read the tile for a point and print DEM5 + DEM10 values.
fn check_point(
    out: &Path,
    grid5: &TileGrid,
    grid10: &GridInfo,
    lat: f64,
    lon: f64,
) -> anyhow::Result<()> {
    let (gx, gy) = grid5.global_cell(lat, lon);
    let (tx, ty, px, py) = grid5.tile_of(gx, gy);
    let dem5 = read_tile_value(&out.join("dem5"), tx, ty, px, py)?;

    let g10 = TileGrid::new(
        grid10.origin_lat,
        grid10.origin_lon,
        grid10.step_lat,
        grid10.step_lon,
    );
    let (gx10, gy10) = g10.global_cell(lat, lon);
    let (tx10, ty10, px10, py10) = g10.tile_of(gx10, gy10);
    let dem10 = read_tile_value(&out.join("dem10"), tx10, ty10, px10, py10)?;

    let dem5_desc = dem5
        .map(|e| format!("{e:.1} m"))
        .unwrap_or_else(|| "no data".to_string());
    let dem10_desc = dem10
        .map(|e| format!("{e:.1} m"))
        .unwrap_or_else(|| "no data".to_string());
    println!("check ({lat:.6}, {lon:.6}): DEM5 tile={dem5_desc} | DEM10 tile={dem10_desc}");
    Ok(())
}

fn read_tile_value(
    dir: &Path,
    tx: i64,
    ty: i64,
    px: usize,
    py: usize,
) -> anyhow::Result<Option<f32>> {
    if !dir.exists() {
        return Ok(None);
    }
    let path = dir.join(format!("{ty:06}_{tx:06}.tile"));
    if !path.exists() {
        return Ok(None); // no tile written -> all nodata
    }
    let tf = TileFile::read(&path)?;
    let elev = tf.elevation_raw()?;
    Ok(dequantize(elev[py * TILE_SIZE + px]))
}
