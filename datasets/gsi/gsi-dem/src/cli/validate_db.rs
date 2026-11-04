use std::io::BufWriter;
use std::path::PathBuf;

use clap::Args;
use serde::Serialize;

use crate::db::{GoldenSpec, validate_golden};
use crate::tile::codec::decompress;
use crate::tile::grid::TILE_SIZE;

/// Validate the SQLite database: golden-coordinate regression + coverage /
/// source-distribution report (plan §36-§37).
#[derive(Debug, Args)]
pub struct ValidateDbArgs {
    /// Path to the SQLite elevation database.
    pub db: PathBuf,

    /// Golden coordinates JSON (default tests/golden/elevation.json).
    #[arg(long, default_value = "tests/golden/elevation.json")]
    pub golden: PathBuf,

    /// Write a JSON report here.
    #[arg(long)]
    pub report: Option<PathBuf>,
}

#[derive(Debug, Serialize, Default)]
struct Coverage {
    layer: String,
    tiles: usize,
    cells_valid: u64,
    cells_nodata: u64,
    source_a: u64,
    source_b: u64,
    source_c: u64,
    source_dem10: u64,
}

pub fn run(args: &ValidateDbArgs) -> anyhow::Result<()> {
    // ---- golden regression ----
    let file = std::fs::File::open(&args.golden)?;
    let spec: GoldenSpec = serde_json::from_reader(file)?;
    let checks = validate_golden(&args.db, &spec)?;

    let mut passed = 0usize;
    for c in &checks {
        let mark = if c.passed { "PASS" } else { "FAIL" };
        if c.passed {
            passed += 1;
        }
        println!("[{mark}] {:<28} {}", c.name, c.detail);
    }
    println!("golden: {passed}/{} passed", checks.len());
    let golden_ok = passed == checks.len();

    // ---- coverage / source report ----
    let conn =
        rusqlite::Connection::open(&args.db).map_err(|e| crate::gsi::error::DemError::Db {
            context: format!("open {}", args.db.display()),
            source: e,
        })?;
    let mut coverages = Vec::new();
    for (layer, layer_name) in [(5i64, "DEM5"), (10i64, "DEM10")] {
        let cov = coverage_for(&conn, layer, layer_name)?;
        println!(
            "coverage {layer_name}: {} tiles, {} valid / {} nodata cells  (A={} B={} C={} DEM10={})",
            cov.tiles,
            cov.cells_valid,
            cov.cells_nodata,
            cov.source_a,
            cov.source_b,
            cov.source_c,
            cov.source_dem10
        );
        coverages.push(cov);
    }

    if let Some(path) = &args.report {
        let report = serde_json::json!({
            "golden": {
                "passed": passed,
                "total": checks.len(),
                "checks": checks.iter().map(|c| serde_json::json!({
                    "name": c.name,
                    "lat": c.lat,
                    "lon": c.lon,
                    "expected_m": c.expected_m,
                    "actual_m": c.actual_m,
                    "actual_layer": c.actual_layer,
                    "passed": c.passed,
                })).collect::<Vec<_>>(),
            },
            "coverage": coverages,
        });
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        serde_json::to_writer_pretty(BufWriter::new(std::fs::File::create(path)?), &report)?;
        println!("report written to {}", path.display());
    }

    if !golden_ok {
        anyhow::bail!("golden regression failed");
    }
    Ok(())
}

fn coverage_for(
    conn: &rusqlite::Connection,
    layer: i64,
    layer_name: &str,
) -> anyhow::Result<Coverage> {
    let mut cov = Coverage {
        layer: layer_name.to_string(),
        ..Default::default()
    };
    let mut stmt =
        conn.prepare("SELECT tile_x, tile_y, data FROM elevation_tiles WHERE layer = ?1")?;
    let rows = stmt.query_map([layer], |r| {
        Ok((
            r.get::<_, i64>(0)?,
            r.get::<_, i64>(1)?,
            r.get::<_, Vec<u8>>(2)?,
        ))
    })?;
    for row in rows {
        let (_tx, _ty, blob) = row?;
        let raw = decompress(&blob, TILE_SIZE * TILE_SIZE * 2)?;
        cov.tiles += 1;
        let mut valid = 0u64;
        for chunk in raw.chunks_exact(2) {
            let v = i16::from_le_bytes([chunk[0], chunk[1]]);
            if v != i16::MIN {
                valid += 1;
            }
        }
        cov.cells_valid += valid;
        cov.cells_nodata += (TILE_SIZE * TILE_SIZE) as u64 - valid;
    }

    // source distribution from source_tiles
    let mut src_stmt = conn.prepare("SELECT data FROM source_tiles WHERE layer = ?1")?;
    let src_rows = src_stmt.query_map([layer], |r| r.get::<_, Vec<u8>>(0))?;
    for blob in src_rows {
        let blob = blob?;
        let raw = decompress(&blob, TILE_SIZE * TILE_SIZE)?;
        for &s in &raw {
            match s {
                2 => cov.source_c += 1,
                3 => cov.source_b += 1,
                4 => cov.source_a += 1,
                1 => cov.source_dem10 += 1,
                _ => {}
            }
        }
    }
    Ok(cov)
}
