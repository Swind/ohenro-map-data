use std::path::PathBuf;

use clap::Args;

use crate::gsi::archive::{self, xml_entry_names};
use crate::gsi::model::{DemSource, SampleKind};
use crate::gsi::xml::parse_dem;
use crate::raster::grid::{GridBounds, sample_at};

/// Query elevation at a lat/lon against a GSI DEM zip archive.
#[derive(Debug, Args)]
pub struct QueryArgs {
    /// Path to a GSI DEM zip archive.
    pub path: PathBuf,

    #[arg(long)]
    pub lat: f64,

    #[arg(long)]
    pub lon: f64,

    /// Restrict lookup to one mesh code (e.g. 51346278).
    #[arg(long)]
    pub mesh: Option<String>,
}

pub fn run(args: &QueryArgs) -> anyhow::Result<()> {
    let mut zip = archive::open_archive(&args.path)?;
    let names = xml_entry_names(&mut zip)?;

    let mut found = false;
    for name in &names {
        let entry = archive::read_entry(&mut zip, name)?;
        let raster = parse_dem(name, entry)?;

        if let Some(m) = &args.mesh {
            if &raster.mesh != m {
                continue;
            }
        }
        let bounds = GridBounds::from_raster(&raster);
        if !bounds.contains(args.lat, args.lon) {
            continue;
        }

        found = true;
        let (row, col) = crate::raster::grid::nearest_cell(&raster, args.lat, args.lon)
            .expect("bounds check already passed");
        let sample = sample_at(&raster, row, col);
        let (cell_lat, cell_lon) = crate::raster::grid::cell_center(&raster, row, col);

        println!("mesh:        {}", raster.mesh);
        println!("source:      {}", raster.source);
        println!("survey_date: {}", raster.survey_date);
        println!("cell:        row={} col={} center=({:.6}, {:.6})", row, col, cell_lat, cell_lon);
        match sample {
            Some(s) => {
                let meters = s
                    .meters
                    .map(|v| format!("{:.2} m", v))
                    .unwrap_or_else(|| "N/A".into());
                println!("elevation:   {}", meters);
                println!("kind:        {}", s.kind.as_str());
                if s.kind == SampleKind::Sea {
                    println!("note:        sea cell, elevation normalized to 0 m");
                }
            }
            None => println!("elevation:   N/A (no stored sample at this cell)"),
        }
        println!("note:        nearest-cell lookup; bilinear interpolation is a later phase");
        break;
    }

    if !found {
        println!("no mesh found containing lat={} lon={}", args.lat, args.lon);
        if args.mesh.is_none() {
            println!("(you may need to pick the archive for the correct 2nd-level mesh region)");
        }
    }
    let _ = DemSource::Dem5A;
    Ok(())
}