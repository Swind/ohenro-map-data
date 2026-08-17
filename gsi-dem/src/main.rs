use clap::{Parser, Subcommand};

use gsi_dem::cli;

#[derive(Debug, Parser)]
#[command(
    name = "gsi-dem",
    version,
    about = "GSI DEM converter for Shikoku elevation data"
)]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Debug, Subcommand)]
enum Command {
    /// Inspect a GSI DEM ZIP archive (metadata + sample counts).
    Inspect(cli::inspect::InspectArgs),
    /// Build the SQLite elevation database from `tile` output.
    Build(cli::build::BuildArgs),
    /// Merge DEM5A > DEM5B > DEM5C per mesh.
    Merge(cli::merge::MergeArgs),
    /// Query elevation at a lat/lon (against a ZIP archive).
    Query(cli::query::QueryArgs),
    /// Query elevation at a lat/lon (against the SQLite database).
    QueryDb(cli::query_db::QueryDbArgs),
    /// Render a mesh raster as a debug PNG.
    Render(cli::render::RenderArgs),
    /// Re-cut merged rasters into 256x256 zstd tiles.
    Tile(cli::tile::TileArgs),
    /// Cross-validate DEM5 vs DEM10B raster agreement.
    Validate(cli::validate::ValidateArgs),
    /// Validate the SQLite database (golden coordinates + coverage).
    ValidateDb(cli::validate_db::ValidateDbArgs),
}

fn main() -> anyhow::Result<()> {
    let cli = Cli::parse();
    match cli.command {
        Command::Inspect(args) => cli::inspect::run(&args),
        Command::Build(args) => cli::build::run(&args),
        Command::Merge(args) => cli::merge::run(&args),
        Command::Query(args) => cli::query::run(&args),
        Command::QueryDb(args) => cli::query_db::run(&args),
        Command::Render(args) => cli::render::run(&args),
        Command::Tile(args) => cli::tile::run(&args),
        Command::Validate(args) => cli::validate::run(&args),
        Command::ValidateDb(args) => cli::validate_db::run(&args),
    }
}
