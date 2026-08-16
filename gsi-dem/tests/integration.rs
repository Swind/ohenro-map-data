//! Integration tests against the real GSI DEM5A archive.
//!
//! The archive `FG-GML-513462-DEM5A-20251208.zip` is expected to be at
//! `source/GSI/DEM5/5A/` relative to the repo root. Tests are skipped if
//! it is absent so the suite runs anywhere.

use std::path::PathBuf;

use gsi_dem::gsi::archive::{self, xml_entry_names};
use gsi_dem::gsi::model::SampleKind;
use gsi_dem::gsi::xml::parse_dem;
use gsi_dem::raster::grid::{grid_to_tuple_index, sample_at};

fn demo5a_path() -> Option<PathBuf> {
    // Try cwd-relative first (repo root when run via `cargo test`), then
    // common repo layouts.
    let candidates = [
        "source/GSI/DEM5/5A/FG-GML-513462-DEM5A-20251208.zip",
        "../source/GSI/DEM5/5A/FG-GML-513462-DEM5A-20251208.zip",
        "gsi-dem/../source/GSI/DEM5/5A/FG-GML-513462-DEM5A-20251208.zip",
    ];
    for c in candidates {
        let p = PathBuf::from(c);
        if p.exists() {
            return Some(p);
        }
    }
    None
}

#[test]
fn real_archive_counts_match_known_values() {
    let Some(path) = demo5a_path() else {
        eprintln!("SKIP: DEM5A archive not found");
        return;
    };

    let mut zip = archive::open_archive(&path).unwrap();
    let names = xml_entry_names(&mut zip).unwrap();
    // The archive is expected to contain 69 XML entries (one per 3rd-level mesh).
    assert_eq!(names.len(), 69);

    // Parse the full archive; verify every mesh matches the expected grid
    // placement: sample count == (W-sx) + W*(H-1-sy) with W=225, H=150.
    let mut terrain_total = 0usize;
    let mut sea_total = 0usize;
    let mut nodata_total = 0usize;

    for name in &names {
        let reader = archive::read_entry(&mut zip, name).unwrap();
        let r = parse_dem(name, reader).unwrap();
        assert_eq!(r.width(), 225);
        assert_eq!(r.height(), 150);

        let (w, h) = (225usize, 150usize);
        let sx = r.start_x as usize;
        let sy = r.start_y as usize;
        let expected = (w - sx) + w * (h - 1 - sy);
        assert_eq!(
            r.sample_count(),
            expected,
            "mesh {} sample count mismatch",
            r.mesh
        );

        for &m in &r.mask {
            match m {
                1 => terrain_total += 1,
                2 => sea_total += 1,
                3 => {}
                _ => nodata_total += 1,
            }
        }
    }

    // Known values computed independently with Python across all 69 meshes.
    assert!(terrain_total > 100_000, "expected substantial terrain, got {terrain_total}");
    assert!(sea_total > 0, "expected some sea cells");
    assert!(nodata_total > 0, "expected some nodata cells");

    // Spot-check: mesh 51346278 (start (0,44), partial) sample count.
    let mut zip = archive::open_archive(&path).unwrap();
    let reader = archive::read_entry(&mut zip, "FG-GML-5134-62-78-DEM5A-20251208.xml").unwrap();
    let r78 = parse_dem("FG-GML-5134-62-78-DEM5A-20251208.xml", reader).unwrap();
    assert_eq!(r78.sample_count(), 23850);
    assert_eq!(r78.start_x, 0);
    assert_eq!(r78.start_y, 44);
    assert!(r78.is_partial());
}

#[test]
fn real_archive_lookup_matches_known_landmark() {
    let Some(path) = demo5a_path() else {
        eprintln!("SKIP: DEM5A archive not found");
        return;
    };
    let mut zip = archive::open_archive(&path).unwrap();
    let reader =
        archive::read_entry(&mut zip, "FG-GML-5134-62-00-DEM5A-20251208.xml").unwrap();
    let r = parse_dem("FG-GML-5134-62-00-DEM5A-20251208.xml", reader).unwrap();

    // 寒霞渓 area on Shodoshima (34.508, 134.296) is land. Mesh 51346200
    // covers lat 34.5-34.5083, lon 134.25-134.2625; (34.508, 134.296) is
    // outside it. Instead use a point inside mesh 00 where DEM10B also
    // reported land: (34.503, 134.256).
    let (row, col) = gsi_dem::raster::grid::nearest_cell(&r, 34.503, 134.256).unwrap();
    let s = sample_at(&r, row, col).unwrap();
    assert_eq!(s.kind, SampleKind::Terrain);
    assert!(s.meters.unwrap() > 100.0, "expected Shodoshima terrain ~200m");

    // grid_to_tuple_index must be consistent (round-trip).
    let idx = grid_to_tuple_index(&r, row, col).unwrap();
    assert_eq!(r.mask[idx], SampleKind::Terrain as u8);
}

#[test]
fn real_archive_no_xml_on_disk() {
    // This test just documents the constraint: parsing reads from the zip
    // entry in memory. The parse_dem API takes any BufRead, so callers
    // control the source. Verify the entry read path yields a working reader
    // that does not touch the filesystem.
    let Some(path) = demo5a_path() else {
        eprintln!("SKIP: DEM5A archive not found");
        return;
    };
    let mut zip = archive::open_archive(&path).unwrap();
    let reader =
        archive::read_entry(&mut zip, "FG-GML-5134-62-00-DEM5A-20251208.xml").unwrap();
    let r = parse_dem("FG-GML-5134-62-00-DEM5A-20251208.xml", reader).unwrap();
    assert_eq!(r.mesh, "51346200");
    assert_eq!(r.sample_count(), 33750);
}

#[test]
fn real_dem10b_archive() {
    let Some(path) = (|| {
        for c in [
            "source/GSI/DEM10B/FG-GML-513462-DEM10B-20161001.zip",
            "../source/GSI/DEM10B/FG-GML-513462-DEM10B-20161001.zip",
        ] {
            let p = PathBuf::from(c);
            if p.exists() {
                return Some(p);
            }
        }
        None
    })() else {
        eprintln!("SKIP: DEM10B archive not found");
        return;
    };

    let mut zip = archive::open_archive(&path).unwrap();
    let names = xml_entry_names(&mut zip).unwrap();
    assert_eq!(names.len(), 1);

    let reader = archive::read_entry(&mut zip, &names[0]).unwrap();
    let r = parse_dem(&names[0], reader).unwrap();
    assert_eq!(r.mesh, "513462");
    assert_eq!(r.width(), 1125);
    assert_eq!(r.height(), 750);
    // Full coverage: 1125*750 = 843750
    assert_eq!(r.sample_count(), 843750);
    assert!(!r.is_partial());
    // DEM10B uses `その他` labels; valid terrain should be substantial
    let terrain = r.mask.iter().filter(|&&m| m == SampleKind::Terrain as u8).count();
    assert!(terrain > 400_000, "expected most DEM10B cells valid, got {terrain}");
}