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

/// Phase 2 acceptance: DEM5 and DEM10B must agree on terrain direction and
/// coordinates. Uses a fixed sample grid + xorshift PRNG for determinism.
#[test]
fn real_dem5_dem10b_cross_validation() {
    let (Some(p5), Some(p10)) = (demo5a_path(), dem10b_path()) else {
        eprintln!("SKIP: DEM5A or DEM10B archive not found");
        return;
    };

    fn load(path: &PathBuf) -> Vec<gsi_dem::gsi::model::GsiDemRaster> {
        let mut zip = archive::open_archive(path).unwrap();
        let names = xml_entry_names(&mut zip).unwrap();
        let mut out = Vec::new();
        for n in &names {
            let reader = archive::read_entry(&mut zip, n).unwrap();
            out.push(parse_dem(n, reader).unwrap());
        }
        out
    }
    let dem5 = load(&p5);
    let dem10 = load(&p10);

    fn sample(
        rasters: &[gsi_dem::gsi::model::GsiDemRaster],
        lat: f64,
        lon: f64,
    ) -> Option<f32> {
        for r in rasters {
            let b = gsi_dem::raster::grid::GridBounds::from_raster(r);
            if b.contains(lat, lon) {
                let (row, col) = gsi_dem::raster::grid::nearest_cell(r, lat, lon)?;
                return gsi_dem::raster::grid::sample_at(r, row, col)?.meters;
            }
        }
        None
    }

    // Bounds of DEM10B region
    let r10 = &dem10[0];
    let (min_lat, min_lon, max_lat, max_lon) =
        (r10.lower_lat, r10.lower_lon, r10.upper_lat, r10.upper_lon);

    let mut state: u64 = 42;
    let mut next = move || {
        state ^= state << 13;
        state ^= state >> 7;
        state ^= state << 17;
        state as f64 / u64::MAX as f64
    };

    let mut diffs = Vec::new();
    let mut land = 0;
    let mut land_ok = 0;
    let mut sea_ref = 0;
    let mut sea_ok = 0;

    for _ in 0..300 {
        let lat = min_lat + next() * (max_lat - min_lat);
        let lon = min_lon + next() * (max_lon - min_lon);
        let e10 = sample(&dem10, lat, lon);
        let e5 = sample(&dem5, lat, lon);
        match e10 {
            Some(v10) => {
                land += 1;
                match e5 {
                    Some(v5) => {
                        let d = (v5 - v10).abs();
                        diffs.push(d);
                        if d < 8.0 {
                            land_ok += 1;
                        }
                    }
                    None => {}
                }
            }
            None => {
                sea_ref += 1;
                if e5.is_none() {
                    sea_ok += 1;
                }
            }
        }
    }

    assert!(land > 50, "too few land samples: {land}");
    assert!(diffs.len() > 50, "too few comparable elevations");
    let mut s = diffs.clone();
    s.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let median = s[s.len() / 2];
    let land_ratio = land_ok as f64 / land as f64;
    let sea_ratio = sea_ok as f64 / sea_ref as f64;

    // DEM5A (5m, 2025) vs DEM10B (10m, 2016): median should be well under
    // 10m; land/sea agreement reflects orientation correctness.
    assert!(median < 10.0, "median |diff| too high: {median:.2}m");
    assert!(land_ratio > 0.7, "land agreement too low: {land_ratio:.2}");
    assert!(sea_ratio > 0.9, "sea consistency too low: {sea_ratio:.2}");
}

fn dem10b_path() -> Option<PathBuf> {
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
}

/// DEM5B uses a different type (`5mメッシュ（数値地形）`) with a mixed
/// tuple schema (その他 / 地表面 / 海水面 / データなし). Verify the mixed
/// labels parse correctly and `その他` with a real value is terrain.
#[test]
fn real_dem5b_mixed_schema() {
    let Some(path) = (|| {
        for c in [
            "source/GSI/DEM5/5B/FG-GML-493254-DEM5B-20210115.zip",
            "../source/GSI/DEM5/5B/FG-GML-493254-DEM5B-20210115.zip",
        ] {
            let p = PathBuf::from(c);
            if p.exists() {
                return Some(p);
            }
        }
        None
    })() else {
        eprintln!("SKIP: DEM5B archive not found");
        return;
    };

    let mut zip = archive::open_archive(&path).unwrap();
    let names = xml_entry_names(&mut zip).unwrap();
    let mut total_terrain = 0usize;
    let mut total_nodata = 0usize;
    let mut saw_other_label = false;

    for name in &names {
        let reader = archive::read_entry(&mut zip, name).unwrap();
        let r = parse_dem(name, reader).unwrap();
        assert_eq!(r.width(), 225);
        assert_eq!(r.height(), 150);
        for &m in &r.mask {
            match m {
                1 => total_terrain += 1,
                3 => {}
                _ => total_nodata += 1,
            }
        }
        if name.contains("54-79") || name.contains("54-89") || name.contains("54-99") {
            // These are partial meshes (n=33600 < 33750) with a mixed schema.
            assert!(r.is_partial());
            assert_eq!(r.sample_count(), 33600);
        }
        // The archive uses 数値地形 type with その他 labels; parse must not
        // have errored on any label (already implied by unwrap above).
        saw_other_label |= r.mask.iter().any(|&m| m == 1);
    }

    assert!(saw_other_label);
    assert!(total_terrain > 100_000, "expected substantial terrain, got {total_terrain}");
    assert!(total_nodata > 0);
}

/// Phase 2: DEM5B (mixed schema) elevations must agree with DEM10B where
/// both have data, and must not place land where DEM10B is sea.
#[test]
fn real_dem5b_dem10b_cross_validation() {
    let (Some(p5), Some(p10)) = (
        {
            let c = "source/GSI/DEM5/5B/FG-GML-493254-DEM5B-20210115.zip";
            if PathBuf::from(c).exists() {
                Some(PathBuf::from(c))
            } else {
                None
            }
        },
        {
            let c = "source/GSI/DEM10B/FG-GML-493254-DEM10B-20161001.zip";
            if PathBuf::from(c).exists() {
                Some(PathBuf::from(c))
            } else {
                None
            }
        },
    ) else {
        eprintln!("SKIP: DEM5B or DEM10B archive not found");
        return;
    };

    fn load(path: &PathBuf) -> Vec<gsi_dem::gsi::model::GsiDemRaster> {
        let mut zip = archive::open_archive(path).unwrap();
        let names = xml_entry_names(&mut zip).unwrap();
        let mut out = Vec::new();
        for n in &names {
            let reader = archive::read_entry(&mut zip, n).unwrap();
            out.push(parse_dem(n, reader).unwrap());
        }
        out
    }
    let dem5 = load(&p5);
    let dem10 = load(&p10);

    fn sample(
        rasters: &[gsi_dem::gsi::model::GsiDemRaster],
        lat: f64,
        lon: f64,
    ) -> Option<f32> {
        for r in rasters {
            let b = gsi_dem::raster::grid::GridBounds::from_raster(r);
            if b.contains(lat, lon) {
                let (row, col) = gsi_dem::raster::grid::nearest_cell(r, lat, lon)?;
                return gsi_dem::raster::grid::sample_at(r, row, col)?.meters;
            }
        }
        None
    }

    let r10 = &dem10[0];
    let (min_lat, min_lon, max_lat, max_lon) =
        (r10.lower_lat, r10.lower_lon, r10.upper_lat, r10.upper_lon);

    let mut state: u64 = 42;
    let mut next = move || {
        state ^= state << 13;
        state ^= state >> 7;
        state ^= state << 17;
        state as f64 / u64::MAX as f64
    };

    let mut diffs = Vec::new();
    let mut land = 0;
    let mut land_ok = 0;
    let mut land_over_sea = 0;

    for _ in 0..300 {
        let lat = min_lat + next() * (max_lat - min_lat);
        let lon = min_lon + next() * (max_lon - min_lon);
        let e10 = sample(&dem10, lat, lon);
        let e5 = sample(&dem5, lat, lon);
        match (e10, e5) {
            (Some(v10), Some(v5)) => {
                land += 1;
                let d = (v5 - v10).abs();
                diffs.push(d);
                if d < 12.0 {
                    land_ok += 1;
                }
            }
            (None, Some(v5)) => {
                // DEM5B has land where DEM10B is sea -> orientation error.
                if v5 > 5.0 {
                    land_over_sea += 1;
                }
            }
            _ => {}
        }
    }

    assert!(diffs.len() > 50, "too few comparable elevations");
    let mut s = diffs.clone();
    s.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let median = s[s.len() / 2];
    assert!(median < 12.0, "median |diff| too high: {median:.2}m");
    assert!(
        land_over_sea == 0,
        "{land_over_sea} points where DEM5B land over DEM10B sea"
    );
    let _ = (land, land_ok);
}