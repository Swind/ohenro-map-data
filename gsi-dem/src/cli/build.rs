use std::path::PathBuf;

use clap::Args;

use crate::db::{GridReport, write_db};

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
}

pub fn run(args: &BuildArgs) -> anyhow::Result<()> {
    let file = std::fs::File::open(&args.grid)?;
    let grid: GridReport = serde_json::from_reader(file)?;
    write_db(&args.tiles, &grid, &args.output)?;
    Ok(())
}
