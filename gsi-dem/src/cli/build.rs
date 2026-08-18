use std::path::PathBuf;

use clap::Args;

use crate::db::{GridReport, LAYER_DEM5, LAYER_DEM10, write_db_layers};

/// Build the SQLite elevation database from a `tile` output directory.
#[derive(Debug, Args)]
pub struct BuildArgs {
    /// Directory written by `tile` (contains dem5/ and dem10/ subdirs).
    #[arg(long)]
    pub tiles: PathBuf,

    /// Grid geometry JSON report written by `tile --report`.
    #[arg(long)]
    pub grid: PathBuf,

    /// Output SQLite database path.
    #[arg(long, default_value = "output/shikoku-elevation.sqlite")]
    pub output: PathBuf,

    /// Layers to write (repeatable). Defaults to both dem5 and dem10.
    /// Use `--layer 10` for a small DEM10-only database.
    #[arg(long = "layer", value_parser = clap::value_parser!(i64))]
    pub layers: Vec<i64>,
}

pub fn run(args: &BuildArgs) -> anyhow::Result<()> {
    let file = std::fs::File::open(&args.grid)?;
    let grid: GridReport = serde_json::from_reader(file)?;
    if args.layers.is_empty() {
        write_db_layers(&args.tiles, &grid, &args.output, &[LAYER_DEM5, LAYER_DEM10])?;
    } else {
        write_db_layers(&args.tiles, &grid, &args.output, &args.layers)?;
    }
    Ok(())
}
