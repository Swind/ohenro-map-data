use std::io::BufReader;
use std::path::PathBuf;

use clap::Args;

use crate::gsi::archive::{self, xml_entry_names};
use crate::gsi::xml::parse_dem;

/// Inspect a GSI DEM ZIP archive without extracting XML to disk.
#[derive(Debug, Args)]
pub struct InspectArgs {
    /// Path to a GSI DEM zip archive.
    pub path: PathBuf,

    /// Show detailed per-mesh sample-kind breakdown.
    #[arg(long)]
    pub verbose: bool,

    /// Only report meshes whose grid has partial (fewer-than-full) coverage.
    #[arg(long)]
    pub partial_only: bool,
}

pub fn run(args: &InspectArgs) -> anyhow::Result<()> {
    let mut zip = archive::open_archive(&args.path)?;
    let names = xml_entry_names(&mut zip)?;

    println!("Archive: {}", args.path.display());
    println!("XML entries: {}", names.len());
    println!();

    let mut total_rasters = 0usize;
    let mut total_samples = 0usize;
    let mut partial = 0usize;

    for name in &names {
        let entry = archive::read_entry(&mut zip, name)?;
        let raster = parse_dem(name, entry)?;

        if args.partial_only && !raster.is_partial() {
            continue;
        }

        total_rasters += 1;
        total_samples += raster.sample_count();
        if raster.is_partial() {
            partial += 1;
        }

        print_raster(&raster, args.verbose);
    }

    println!();
    println!("Summary: {} rasters, {} samples total, {} partial-coverage meshes", total_rasters, total_samples, partial);
    Ok(())
}

fn print_raster(r: &crate::gsi::model::GsiDemRaster, verbose: bool) {
    println!(
        "mesh:       {}  ({})",
        r.mesh, r.entry_name
    );
    println!("  source:   {}", r.source);
    println!("  date:     {}", r.survey_date);
    println!(
        "  bounds:   {} {} -> {} {}  ({} x {})",
        r.lower_lat, r.lower_lon, r.upper_lat, r.upper_lon, r.width(), r.height()
    );
    println!(
        "  grid:     low ({},{}) high ({},{})",
        r.grid_low_x, r.grid_low_y, r.grid_high_x, r.grid_high_y
    );
    println!(
        "  seq:      {} order={} start=({},{})",
        r.sequence_rule, r.sequence_order, r.start_x, r.start_y
    );
    let capacity = r.grid_capacity();
    println!(
        "  samples:  {} / {} ({})",
        r.sample_count(),
        capacity,
        if r.is_partial() { "partial" } else { "full" }
    );
    if verbose {
        for (kind, count) in r.kind_counts() {
            println!("    {}: {}", kind.as_str(), count);
        }
    }
    println!();
}

#[allow(dead_code)]
fn _unused(_: BufReader<Box<dyn std::io::Read>>) {}