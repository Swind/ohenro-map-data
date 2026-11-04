use std::fs::File;
use std::io::{BufRead, BufReader, BufWriter, Write};
use std::path::PathBuf;

use clap::Args;
use serde_json::Value;

use crate::db::ElevationDb;

/// Query newline-delimited JSON points, preserving each input object.
#[derive(Debug, Args)]
pub struct QueryBatchArgs {
    /// Path to the SQLite elevation database.
    pub db: PathBuf,

    /// Input JSONL. Every object must contain numeric `lat` and `lon` fields.
    #[arg(long)]
    pub input: PathBuf,

    /// Output JSONL, with elevation_m, layer, and source_code added.
    #[arg(long)]
    pub output: PathBuf,
}

pub fn run(args: &QueryBatchArgs) -> anyhow::Result<()> {
    let input = BufReader::new(File::open(&args.input)?);
    let output = BufWriter::new(File::create(&args.output)?);
    let mut db = ElevationDb::open(&args.db)?;
    write_results(input, output, &mut db)
}

fn write_results<R: BufRead, W: Write>(
    input: R,
    mut output: W,
    db: &mut ElevationDb,
) -> anyhow::Result<()> {
    let mut count = 0usize;
    for (line_number, line) in input.lines().enumerate() {
        let line = line?;
        if line.trim().is_empty() {
            continue;
        }
        let mut value: Value = serde_json::from_str(&line)
            .map_err(|e| anyhow::anyhow!("input line {}: invalid JSON: {e}", line_number + 1))?;
        let object = value.as_object_mut().ok_or_else(|| {
            anyhow::anyhow!("input line {}: expected a JSON object", line_number + 1)
        })?;
        let lat = object.get("lat").and_then(Value::as_f64).ok_or_else(|| {
            anyhow::anyhow!("input line {}: lat must be a number", line_number + 1)
        })?;
        let lon = object.get("lon").and_then(Value::as_f64).ok_or_else(|| {
            anyhow::anyhow!("input line {}: lon must be a number", line_number + 1)
        })?;
        let sample = db.sample(lat, lon)?;
        object.insert(
            "elevation_m".into(),
            sample.meters.map(Value::from).unwrap_or(Value::Null),
        );
        object.insert(
            "layer".into(),
            sample.layer.map(Value::from).unwrap_or(Value::Null),
        );
        object.insert(
            "source_code".into(),
            sample.source_code.map(Value::from).unwrap_or(Value::Null),
        );
        serde_json::to_writer(&mut output, &value)?;
        output.write_all(b"\n")?;
        count += 1;
    }
    output.flush()?;
    println!("query-batch: wrote {count} points");
    Ok(())
}
