use clap::{Parser, Subcommand};

use gsi_dem::cli;

#[derive(Debug, Parser)]
#[command(name = "gsi-dem", version, about = "GSI DEM converter for Shikoku elevation data")]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Debug, Subcommand)]
enum Command {
    /// Inspect a GSI DEM ZIP archive (metadata + sample counts).
    Inspect(cli::inspect::InspectArgs),
    /// Query elevation at a lat/lon.
    Query(cli::query::QueryArgs),
    /// Render a mesh raster as a debug PNG.
    Render(cli::render::RenderArgs),
}

fn main() -> anyhow::Result<()> {
    let cli = Cli::parse();
    match cli.command {
        Command::Inspect(args) => cli::inspect::run(&args),
        Command::Query(args) => cli::query::run(&args),
        Command::Render(args) => cli::render::run(&args),
    }
}