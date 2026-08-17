//! SQLite container for the tiled elevation database (plan §23-§25, Phase 6).
//!
//! Schema (from the plan):
//! - `metadata(key PK, value)` — grid geometry, encoding, compression.
//! - `elevation_tiles(layer, tile_x, tile_y, width, height, data)` —
//!   `data` = zstd(int16[65536] LE); `layer` 5 = DEM5, 10 = DEM10.
//! - `source_tiles(layer, tile_x, tile_y, data)` — `data` = zstd(u8[65536]
//!   plan §16 source codes).

use std::path::Path;
use std::time::{SystemTime, UNIX_EPOCH};

use rusqlite::{Connection, OptionalExtension, params};
use serde::{Deserialize, Serialize};

use crate::gsi::error::{DemError, DemResult};
use crate::tile::codec::{compress, decompress, dequantize};
use crate::tile::grid::{TILE_SIZE, TileGrid};
use crate::tile::tilefile::TileFile;

pub const LAYER_DEM5: i64 = 5;
pub const LAYER_DEM10: i64 = 10;

/// Grid geometry as written by the `tile` command's report.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GridReport {
    pub grid_dem5: GridInfo,
    pub grid_dem10: GridInfo,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct GridInfo {
    pub origin_lat: f64,
    pub origin_lon: f64,
    pub step_lat: f64,
    pub step_lon: f64,
    pub tile_size: usize,
}

fn db_err(context: &str) -> impl FnOnce(rusqlite::Error) -> DemError {
    let context = context.to_string();
    move |source| DemError::Db { context, source }
}

fn open(path: &Path) -> DemResult<Connection> {
    Connection::open(path).map_err(db_err(&format!("open {}", path.display())))
}

/// Build the SQLite database from a `tile` output directory.
pub fn write_db(tiles_dir: &Path, grid: &GridReport, output: &Path) -> DemResult<()> {
    if let Some(parent) = output.parent() {
        std::fs::create_dir_all(parent).map_err(|e| DemError::Io {
            context: format!("create {}", parent.display()),
            source: e,
        })?;
    }
    let conn = open(output)?;
    conn.execute_batch(
        "PRAGMA journal_mode=OFF;
         PRAGMA synchronous=OFF;
         CREATE TABLE IF NOT EXISTS metadata (
             key   TEXT PRIMARY KEY,
             value TEXT NOT NULL
         );
         CREATE TABLE IF NOT EXISTS elevation_tiles (
             layer  INTEGER NOT NULL,
             tile_x INTEGER NOT NULL,
             tile_y INTEGER NOT NULL,
             width  INTEGER NOT NULL,
             height INTEGER NOT NULL,
             data   BLOB NOT NULL,
             PRIMARY KEY (layer, tile_x, tile_y)
         );
         CREATE TABLE IF NOT EXISTS source_tiles (
             layer  INTEGER NOT NULL,
             tile_x INTEGER NOT NULL,
             tile_y INTEGER NOT NULL,
             data   BLOB NOT NULL,
             PRIMARY KEY (layer, tile_x, tile_y)
         );",
    )
    .map_err(db_err("schema"))?;

    // metadata
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    let mut meta = conn
        .prepare("INSERT INTO metadata (key, value) VALUES (?1, ?2)")
        .map_err(db_err("prepare metadata"))?;
    let mut insert_meta = |k: &str, v: &str| -> DemResult<()> {
        meta.execute(params![k, v])
            .map_err(db_err("insert metadata"))?;
        Ok(())
    };
    insert_meta("format_version", "1")?;
    insert_meta("created_at", &now.to_string())?;
    insert_meta("dataset", "shikoku")?;
    insert_meta("horizontal_datum", "JGD2024")?;
    insert_meta("tile_size", &TILE_SIZE.to_string())?;
    insert_meta("compression", "zstd")?;
    insert_meta("encoding", "int16_meters")?;
    for (prefix, gi) in [("dem5", &grid.grid_dem5), ("dem10", &grid.grid_dem10)] {
        insert_meta(&format!("{prefix}.origin_lat"), &gi.origin_lat.to_string())?;
        insert_meta(&format!("{prefix}.origin_lon"), &gi.origin_lon.to_string())?;
        insert_meta(&format!("{prefix}.step_lat"), &gi.step_lat.to_string())?;
        insert_meta(&format!("{prefix}.step_lon"), &gi.step_lon.to_string())?;
    }
    drop(meta);

    // tiles
    let mut ins_elev = conn
        .prepare(
            "INSERT INTO elevation_tiles (layer, tile_x, tile_y, width, height, data)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
        )
        .map_err(db_err("prepare elevation insert"))?;
    let mut ins_src = conn
        .prepare("INSERT INTO source_tiles (layer, tile_x, tile_y, data) VALUES (?1, ?2, ?3, ?4)")
        .map_err(db_err("prepare source insert"))?;

    conn.execute("BEGIN", [])
        .map_err(db_err("begin transaction"))?;

    let mut elev_count = 0u64;
    let mut src_count = 0u64;
    for (layer, dirname) in [(LAYER_DEM5, "dem5"), (LAYER_DEM10, "dem10")] {
        let dir = tiles_dir.join(dirname);
        let mut paths: Vec<_> = std::fs::read_dir(&dir)
            .map_err(|e| DemError::Io {
                context: format!("read {}", dir.display()),
                source: e,
            })?
            .filter_map(|e| e.ok())
            .map(|e| e.path())
            .filter(|p| p.extension().is_some_and(|x| x == "tile"))
            .collect();
        paths.sort();
        for p in paths {
            let tf = TileFile::read(&p)?;
            if tf.layer as i64 != layer {
                return Err(DemError::Parse {
                    context: format!("{}: layer mismatch", p.display()),
                });
            }
            ins_elev
                .execute(params![
                    layer,
                    tf.tile_x,
                    tf.tile_y,
                    TILE_SIZE as i64,
                    TILE_SIZE as i64,
                    &tf.elevation_zstd,
                ])
                .map_err(db_err("insert elevation"))?;
            elev_count += 1;
            let src_zstd = compress(&tf.source)?;
            ins_src
                .execute(params![layer, tf.tile_x, tf.tile_y, src_zstd])
                .map_err(db_err("insert source"))?;
            src_count += 1;
        }
    }
    conn.execute("COMMIT", []).map_err(db_err("commit"))?;

    let size = std::fs::metadata(output).map(|m| m.len()).unwrap_or(0);
    println!(
        "wrote {} ({} elevation tiles, {} source tiles, {:.1} MB)",
        output.display(),
        elev_count,
        src_count,
        size as f64 / 1e6
    );
    Ok(())
}

/// Result of a runtime elevation query.
#[derive(Debug, Clone, PartialEq)]
pub struct QueryResult {
    pub meters: Option<f32>,
    /// 5 = DEM5, 10 = DEM10.
    pub layer: Option<u8>,
    /// plan §16 source code (0-4) if the covering tile stores one.
    pub source_code: Option<u8>,
}

/// Golden coordinate spec (plan §36).
#[derive(Debug, Clone, Deserialize)]
pub struct GoldenSpec {
    #[serde(rename = "tolerance_m")]
    pub tolerance: GoldenTolerance,
    pub points: Vec<GoldenPoint>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct GoldenTolerance {
    pub dem5: f64,
    pub dem10: f64,
}

#[derive(Debug, Clone, Deserialize)]
pub struct GoldenPoint {
    pub name: String,
    pub lat: f64,
    pub lon: f64,
    pub expected_m: f64,
    pub layer: String,
}

/// Result of one golden point check.
#[derive(Debug, Clone)]
pub struct GoldenCheck {
    pub name: String,
    pub lat: f64,
    pub lon: f64,
    pub expected_m: f64,
    pub actual_m: Option<f32>,
    pub actual_layer: Option<u8>,
    pub passed: bool,
    pub detail: String,
}

/// Run golden-coordinate regression against a SQLite database.
pub fn validate_golden(db_path: &Path, spec: &GoldenSpec) -> DemResult<Vec<GoldenCheck>> {
    let mut out = Vec::with_capacity(spec.points.len());
    for p in &spec.points {
        let r = query_db(db_path, p.lat, p.lon)?;
        let tolerance = match p.layer.as_str() {
            "dem10" => spec.tolerance.dem10,
            _ => spec.tolerance.dem5,
        };
        let (passed, detail) = match r.meters {
            Some(m) => {
                let diff = (m as f64 - p.expected_m).abs();
                let layer_name = match r.layer {
                    Some(5) => "DEM5",
                    Some(10) => "DEM10",
                    _ => "?",
                };
                if diff <= tolerance {
                    (
                        true,
                        format!(
                            "ok: {m:.1} m (layer={layer_name}) vs expected {:.1} m (|diff| {diff:.1} <= {tolerance})",
                            p.expected_m
                        ),
                    )
                } else {
                    (
                        false,
                        format!(
                            "FAIL: {m:.1} m (layer={layer_name}) vs expected {:.1} m (|diff| {diff:.1} > {tolerance})",
                            p.expected_m
                        ),
                    )
                }
            }
            None => (false, format!("FAIL: no data at ({}, {})", p.lat, p.lon)),
        };
        out.push(GoldenCheck {
            name: p.name.clone(),
            lat: p.lat,
            lon: p.lon,
            expected_m: p.expected_m,
            actual_m: r.meters,
            actual_layer: r.layer,
            passed,
            detail,
        });
    }
    Ok(out)
}

/// Runtime lookup: DEM5 first, DEM10B fallback (plan §17/§25).
pub fn query_db(path: &Path, lat: f64, lon: f64) -> DemResult<QueryResult> {
    let conn = open(path)?;
    let meta = |k: &str| -> DemResult<Option<String>> {
        conn.query_row(
            "SELECT value FROM metadata WHERE key = ?1",
            params![k],
            |r| r.get(0),
        )
        .optional()
        .map_err(db_err("read metadata"))
    };

    let g5 = TileGrid::new(
        meta("dem5.origin_lat")?.and_then(parse).unwrap_or(f64::NAN),
        meta("dem5.origin_lon")?.and_then(parse).unwrap_or(f64::NAN),
        meta("dem5.step_lat")?.and_then(parse).unwrap_or(f64::NAN),
        meta("dem5.step_lon")?.and_then(parse).unwrap_or(f64::NAN),
    );
    if g5.step_lat.is_nan() {
        // no DEM5 grid metadata
    } else if let Some(r) = sample_layer(&conn, LAYER_DEM5, &g5, lat, lon)? {
        return Ok(r);
    }

    let g10 = TileGrid::new(
        meta("dem10.origin_lat")?
            .and_then(parse)
            .unwrap_or(f64::NAN),
        meta("dem10.origin_lon")?
            .and_then(parse)
            .unwrap_or(f64::NAN),
        meta("dem10.step_lat")?.and_then(parse).unwrap_or(f64::NAN),
        meta("dem10.step_lon")?.and_then(parse).unwrap_or(f64::NAN),
    );
    if g10.step_lat.is_nan() {
        // no DEM10 grid metadata
    } else if let Some(r) = sample_layer(&conn, LAYER_DEM10, &g10, lat, lon)? {
        return Ok(r);
    }

    Ok(QueryResult {
        meters: None,
        layer: None,
        source_code: None,
    })
}

fn parse(s: String) -> Option<f64> {
    s.trim().parse().ok()
}

fn sample_layer(
    conn: &Connection,
    layer: i64,
    grid: &TileGrid,
    lat: f64,
    lon: f64,
) -> DemResult<Option<QueryResult>> {
    let (gx, gy) = grid.global_cell(lat, lon);
    if gx < 0 || gy < 0 {
        return Ok(None);
    }
    let (tx, ty, px, py) = grid.tile_of(gx, gy);

    let blob: Option<Vec<u8>> = conn
        .query_row(
            "SELECT data FROM elevation_tiles WHERE layer = ?1 AND tile_x = ?2 AND tile_y = ?3",
            params![layer, tx, ty],
            |r| r.get(0),
        )
        .optional()
        .map_err(db_err("read elevation tile"))?;
    let Some(blob) = blob else {
        return Ok(None);
    };
    let raw = decompress(&blob, TILE_SIZE * TILE_SIZE * 2)?;
    let idx = py * TILE_SIZE + px;
    let cell = i16::from_le_bytes([raw[idx * 2], raw[idx * 2 + 1]]);
    let Some(meters) = dequantize(cell) else {
        return Ok(None); // DEM5/10 nodata -> try next layer
    };

    let source_code = conn
        .query_row(
            "SELECT data FROM source_tiles WHERE layer = ?1 AND tile_x = ?2 AND tile_y = ?3",
            params![layer, tx, ty],
            |r| r.get(0),
        )
        .optional()
        .map_err(db_err("read source tile"))?
        .and_then(|s: Vec<u8>| decompress(&s, TILE_SIZE * TILE_SIZE).ok())
        .and_then(|d| d.get(idx).copied());

    Ok(Some(QueryResult {
        meters: Some(meters),
        layer: Some(layer as u8),
        source_code,
    }))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::tile::grid::ELEV_NODATA;
    use crate::tile::tilefile::TileFile;

    fn temp_dir(tag: &str) -> std::path::PathBuf {
        let d = std::env::temp_dir().join(format!("gsi-dem-db-test-{tag}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&d);
        std::fs::create_dir_all(&d).unwrap();
        d
    }

    fn write_tile(dir: &Path, layer: u8, tx: u32, ty: u32, cell: usize, elev: i16, source: u8) {
        let mut elev_bytes = vec![0u8; TILE_SIZE * TILE_SIZE * 2];
        for (i, chunk) in elev_bytes.chunks_exact_mut(2).enumerate() {
            let v = if i == cell { elev } else { ELEV_NODATA };
            chunk.copy_from_slice(&v.to_le_bytes());
        }
        let mut src = vec![0u8; TILE_SIZE * TILE_SIZE];
        src[cell] = source;
        let tf = TileFile {
            layer,
            tile_x: tx,
            tile_y: ty,
            elevation_zstd: compress(&elev_bytes).unwrap(),
            source: src,
        };
        tf.write(&dir.join(format!("{ty:06}_{tx:06}.tile")))
            .unwrap();
    }

    #[test]
    fn build_and_query_round_trip() {
        let root = temp_dir("rt");
        let tiles = root.join("tiles");
        std::fs::create_dir_all(tiles.join("dem5")).unwrap();
        std::fs::create_dir_all(tiles.join("dem10")).unwrap();

        let origin_lat = 34.508333333;
        let origin_lon = 134.25;
        let step = 1.0 / 18000.0;
        let grid = GridReport {
            grid_dem5: GridInfo {
                origin_lat,
                origin_lon,
                step_lat: step,
                step_lon: step,
                tile_size: TILE_SIZE,
            },
            grid_dem10: GridInfo {
                origin_lat,
                origin_lon,
                step_lat: step / 2.0,
                step_lon: step / 2.0,
                tile_size: TILE_SIZE,
            },
        };
        let grid_path = root.join("grid.json");
        std::fs::write(&grid_path, serde_json::to_vec(&grid).unwrap()).unwrap();

        // DEM5 tile (0,0): global cell (100,100) holds 123m, source=DEM5A.
        write_tile(&tiles.join("dem5"), 5, 0, 0, 100 * TILE_SIZE + 100, 123, 4);
        // DEM10 tile (0,0): cell (100,100) holds 99m (used as fallback).
        write_tile(&tiles.join("dem10"), 10, 0, 0, 100 * TILE_SIZE + 100, 99, 1);

        let db_path = root.join("elev.sqlite");
        write_db(&tiles, &grid, &db_path).unwrap();

        // Center of global cell (100,100) in the DEM5 grid.
        let lat = origin_lat - (100.0 + 0.5) * step;
        let lon = origin_lon + (100.0 + 0.5) * step;
        let r = query_db(&db_path, lat, lon).unwrap();
        assert_eq!(r.meters, Some(123.0));
        assert_eq!(r.layer, Some(5));
        assert_eq!(r.source_code, Some(4));

        // A nodata cell in DEM5 -> DEM10 fallback. The center of DEM10 cell
        // (100,100) is at 50.25 DEM5 steps below the origin -> inside DEM5
        // cell (50,50) which is nodata; DEM10 holds 99 there.
        let lat = origin_lat - 50.25 * step;
        let lon = origin_lon + 50.25 * step;
        let r = query_db(&db_path, lat, lon).unwrap();
        assert_eq!(r.meters, Some(99.0));
        assert_eq!(r.layer, Some(10));
    }
}
