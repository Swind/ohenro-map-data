//! Regression tests for the `export-vrt` exporter (docs §12.1).
//!
//! Builds synthetic SQLite databases via `write_db_layers`, exports them with
//! `cli::export_vrt::run`, and verifies the raw Int16 raster placement,
//! north-up orientation, tile-boundary adjacency, NODATA fill for missing
//! tiles, and the malformed-blob error path.

use std::path::{Path, PathBuf};

use gsi_dem::cli::export_vrt::{ExportVrtArgs, run};
use gsi_dem::db::{GridInfo, GridReport, write_db_layers};
use gsi_dem::tile::codec::compress;
use gsi_dem::tile::grid::{ELEV_NODATA, TILE_SIZE};
use gsi_dem::tile::tilefile::TileFile;

fn temp_dir(tag: &str) -> PathBuf {
    let d = std::env::temp_dir().join(format!(
        "gsi-dem-export-vrt-{tag}-{}",
        std::process::id()
    ));
    let _ = std::fs::remove_dir_all(&d);
    std::fs::create_dir_all(&d).unwrap();
    d
}

fn step() -> f64 {
    1.0 / 9000.0
}

fn grid_report() -> GridReport {
    let g = GridInfo {
        origin_lat: 34.5,
        origin_lon: 134.0,
        step_lat: step(),
        step_lon: step(),
        tile_size: TILE_SIZE,
    };
    GridReport {
        grid_dem5: g.clone(),
        grid_dem10: g,
    }
}

/// Write a synthetic .tile file where only `cell` holds `elev` (rest NODATA).
fn write_tile(dir: &Path, tx: u32, ty: u32, cell: usize, elev: i16) {
    write_tile_cells(dir, tx, ty, &[(cell, elev)]);
}

/// Write a tile with several specific cells set (rest NODATA).
fn write_tile_cells(dir: &Path, tx: u32, ty: u32, cells: &[(usize, i16)]) {
    let mut elev_bytes = vec![0u8; TILE_SIZE * TILE_SIZE * 2];
    for (i, chunk) in elev_bytes.chunks_exact_mut(2).enumerate() {
        let v = if let Some((_, e)) = cells.iter().find(|(c, _)| *c == i) {
            *e
        } else {
            ELEV_NODATA
        };
        chunk.copy_from_slice(&v.to_le_bytes());
    }
    let tf = TileFile {
        layer: 10,
        tile_x: tx,
        tile_y: ty,
        elevation_zstd: compress(&elev_bytes).unwrap(),
        source: vec![0u8; TILE_SIZE * TILE_SIZE],
    };
    tf.write(&dir.join(format!("{ty:06}_{tx:06}.tile")))
        .unwrap();
}

/// The `write_db`/`write_db_layers` builder expects tiles under a `dem10/`
/// subdirectory of the supplied dir.
fn dem10_dir(tiles: &Path) -> PathBuf {
    let d = tiles.join("dem10");
    std::fs::create_dir_all(&d).unwrap();
    d
}

fn build_db(tiles_dir: &Path) -> PathBuf {
    let root = temp_dir("db");
    let grid = grid_report();
    let grid_path = root.join("grid.json");
    std::fs::write(&grid_path, serde_json::to_vec(&grid).unwrap()).unwrap();
    let db_path = root.join("elev.sqlite");
    write_db_layers(tiles_dir, &grid, &db_path, &[10]).unwrap();
    db_path
}

fn read_raw(path: &Path, width: usize, height: usize) -> Vec<i16> {
    let bytes = std::fs::read(path).unwrap();
    assert_eq!(bytes.len(), width * height * 2);
    bytes
        .chunks_exact(2)
        .map(|c| i16::from_le_bytes([c[0], c[1]]))
        .collect()
}

#[test]
fn exports_tiles_across_four_coordinates_north_up() {
    let root = temp_dir("four");
    let tiles = root.join("tiles");
    std::fs::create_dir_all(&tiles).unwrap();

    // 2x2 tiles: value at cell (0,0) of each is distinctive.
    let d10 = dem10_dir(&tiles);
    write_tile(&d10, 1, 0, 0, 2000); // top-right
    write_tile(&d10, 0, 1, 0, 3000); // bottom-left
    write_tile(&d10, 1, 1, 0, 4000); // bottom-right
    // top-left tile also carries a boundary probe at cell (255,255).
    write_tile_cells(&d10, 0, 0, &[(0, 1000), (TILE_SIZE * TILE_SIZE - 1, 1111)]);

    let db = build_db(&tiles);
    let out_dir = root.join("work");
    let vrt = out_dir.join("dem10.vrt");
    let raw = out_dir.join("dem10.raw");

    run(&ExportVrtArgs {
        database: db,
        layer: 10,
        output: vrt.clone(),
        srs: "EPSG:6668".to_string(),
        force: false,
    })
    .unwrap();

    let width = 2 * TILE_SIZE;
    let height = 2 * TILE_SIZE;
    let data = read_raw(&raw, width, height);

    // North-up: tile row ty=0 is the top (raw rows 0..256).
    // cell (0,0) of each tile sits at raw (ty*256+0, tx*256+0).
    assert_eq!(data[0 * width + 0], 1000, "tile (0,0) top-left");
    assert_eq!(data[0 * width + TILE_SIZE], 2000, "tile (1,0) top-right");
    assert_eq!(
        data[TILE_SIZE * width + 0],
        3000,
        "tile (0,1) bottom-left"
    );
    assert_eq!(
        data[TILE_SIZE * width + TILE_SIZE],
        4000,
        "tile (1,1) bottom-right"
    );
    // boundary adjacency: (0,0).cell(255,255) -> raw (255,255); the next
    // global cell right/down is (0,0) of tile (1,1).
    assert_eq!(data[(TILE_SIZE - 1) * width + (TILE_SIZE - 1)], 1111);
    assert_eq!(data[TILE_SIZE * width + TILE_SIZE], 4000);

    // VRT exists and references the raw by sibling name with LSB byte order.
    let vrt_xml = std::fs::read_to_string(&vrt).unwrap();
    assert!(vrt_xml.contains("dem10.raw"));
    assert!(vrt_xml.contains("ByteOrder>LSB"));
    assert!(vrt_xml.contains("rasterXSize=\"512\""));
    assert!(vrt_xml.contains("rasterYSize=\"512\""));
    assert!(vrt_xml.contains("EPSG:6668"));
}

#[test]
fn missing_tile_is_nodata_not_zero() {
    let root = temp_dir("gap");
    let tiles = root.join("tiles");
    std::fs::create_dir_all(&tiles).unwrap();

    // Extent spans tiles x=0..2 but tile x=1 is missing.
    let d10 = dem10_dir(&tiles);
    write_tile(&d10, 0, 0, 0, 1000);
    write_tile(&d10, 2, 0, 0, 2000);

    let db = build_db(&tiles);
    let out_dir = root.join("work");
    let vrt = out_dir.join("dem10.vrt");
    let raw = out_dir.join("dem10.raw");

    run(&ExportVrtArgs {
        database: db,
        layer: 10,
        output: vrt.clone(),
        srs: "EPSG:6668".to_string(),
        force: false,
    })
    .unwrap();

    let width = 3 * TILE_SIZE;
    let height = 1 * TILE_SIZE;
    let data = read_raw(&raw, width, height);

    // The entire middle tile column must be NODATA, never 0.
    for row in 0..height {
        for col in TILE_SIZE..2 * TILE_SIZE {
            assert_eq!(
                data[row * width + col],
                ELEV_NODATA,
                "missing tile region ({row},{col}) must be NODATA"
            );
        }
    }
    assert_eq!(data[0 * width + 0], 1000);
    assert_eq!(data[0 * width + 2 * TILE_SIZE], 2000);
}

#[test]
fn malformed_blob_returns_error_not_panic() {
    let root = temp_dir("malformed");
    let tiles = root.join("tiles");
    std::fs::create_dir_all(&tiles).unwrap();

    // A .tile whose elevation blob is far shorter than 256*256*2 bytes.
    let short_elev: Vec<u8> = vec![0u8; 8];
    let tf = TileFile {
        layer: 10,
        tile_x: 0,
        tile_y: 0,
        elevation_zstd: compress(&short_elev).unwrap(),
        source: vec![0u8; TILE_SIZE * TILE_SIZE],
    };
    tf.write(&dem10_dir(&tiles).join("000000_000000.tile"))
        .unwrap();

    let db = build_db(&tiles);
    let out_dir = root.join("work");
    let vrt = out_dir.join("dem10.vrt");

    let res = run(&ExportVrtArgs {
        database: db,
        layer: 10,
        output: vrt,
        srs: "EPSG:6668".to_string(),
        force: false,
    });
    assert!(res.is_err(), "malformed blob must produce an error, not panic");
}

#[test]
fn refuses_overwrite_without_force() {
    let root = temp_dir("overwrite");
    let tiles = root.join("tiles");
    std::fs::create_dir_all(&tiles).unwrap();
    write_tile(&dem10_dir(&tiles), 0, 0, 0, 1000);

    let db = build_db(&tiles);
    let out_dir = root.join("work");
    let vrt = out_dir.join("dem10.vrt");
    let args = || ExportVrtArgs {
        database: db.clone(),
        layer: 10,
        output: vrt.clone(),
        srs: "EPSG:6668".to_string(),
        force: false,
    };

    run(&args()).unwrap();
    // second run without --force must fail
    assert!(run(&args()).is_err());
    // with --force it succeeds
    run(&ExportVrtArgs {
        force: true,
        ..args()
    })
    .unwrap();
}
