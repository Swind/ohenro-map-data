//! Golden-coordinate regression against the built SQLite database (plan §36).
//!
//! Skips automatically if the database or golden file is absent, so normal
//! `cargo test` runs stay green without the ~540MB build artifact.

use std::path::PathBuf;

use gsi_dem::db::{GoldenSpec, validate_golden};

fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..")
}

#[test]
fn golden_coordinates_match() {
    let db = repo_root().join("output/shikoku-elevation.sqlite");
    if !db.exists() {
        eprintln!("SKIP: {} not found", db.display());
        return;
    }
    let golden = repo_root().join("gsi-dem/tests/golden/elevation.json");
    let file = std::fs::File::open(&golden).expect("open golden json");
    let spec: GoldenSpec = serde_json::from_reader(file).expect("parse golden json");

    let checks = validate_golden(&db, &spec).expect("validate golden");
    let failed: Vec<_> = checks.iter().filter(|c| !c.passed).collect();
    for c in &failed {
        eprintln!("FAIL: {} at ({}, {}): {}", c.name, c.lat, c.lon, c.detail);
    }
    assert!(
        failed.is_empty(),
        "{}/{} golden checks failed",
        failed.len(),
        checks.len()
    );
}
