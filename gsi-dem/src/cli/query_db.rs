use std::path::PathBuf;

use clap::Args;

use crate::db::ElevationDb;

/// Query the SQLite elevation database at a lat/lon (DEM5 then DEM10 fallback).
#[derive(Debug, Args)]
pub struct QueryDbArgs {
    /// Path to the SQLite elevation database.
    pub db: PathBuf,

    /// Latitude.
    #[arg(long)]
    pub lat: f64,

    /// Longitude.
    #[arg(long)]
    pub lon: f64,
}

pub fn run(args: &QueryDbArgs) -> anyhow::Result<()> {
    let mut db = ElevationDb::open(&args.db)?;
    let r = db.sample(args.lat, args.lon)?;
    match (r.meters, r.layer) {
        (Some(m), Some(layer)) => {
            let layer_name = if layer == 5 { "DEM5" } else { "DEM10" };
            let src = match r.source_code {
                Some(2) => "DEM5C",
                Some(3) => "DEM5B",
                Some(4) => "DEM5A",
                Some(1) => "DEM10B",
                _ => "nodata",
            };
            println!("Elevation: {m:.1} m  (layer={layer_name}, source={src})");
        }
        _ => {
            println!("Elevation: no data");
        }
    }
    Ok(())
}
