use std::io::BufWriter;
use std::path::PathBuf;

use clap::Args;

use crate::gsi::archive::{self, xml_entry_names};
use crate::gsi::model::SampleKind;
use crate::gsi::xml::parse_dem;
use crate::raster::grid::sample_at;

/// Render a DEM raster as a debug PNG (grayscale elevation).
#[derive(Debug, Args)]
pub struct RenderArgs {
    /// Path to a GSI DEM zip archive.
    pub path: PathBuf,

    /// Mesh code to render (e.g. 51346278).
    #[arg(long)]
    pub mesh: String,

    /// Output PNG path.
    #[arg(long, default_value = "render.png")]
    pub output: PathBuf,
}

pub fn run(args: &RenderArgs) -> anyhow::Result<()> {
    let mut zip = archive::open_archive(&args.path)?;
    let names = xml_entry_names(&mut zip)?;

    let mut matched = None;
    for name in &names {
        let entry = archive::read_entry(&mut zip, name)?;
        let raster = parse_dem(name, entry)?;
        if raster.mesh == args.mesh {
            matched = Some(raster);
            break;
        }
    }

    let raster =
        matched.ok_or_else(|| anyhow::anyhow!("mesh {} not found in archive", args.mesh))?;

    let width = raster.width();
    let height = raster.height();
    let mut pixels = vec![0u8; width * height * 3];

    // elevation range for grayscale normalization
    let mut min_e = f32::INFINITY;
    let mut max_e = f32::NEG_INFINITY;
    for &e in &raster.elevation {
        if e.is_finite() {
            min_e = min_e.min(e);
            max_e = max_e.max(e);
        }
    }
    if !min_e.is_finite() {
        min_e = 0.0;
        max_e = 1.0;
    }
    let range = (max_e - min_e).max(1e-6);

    for row in 0..height {
        for col in 0..width {
            // Grid row 0 is the north edge (max_lat), increasing southward.
            // Rendered north-up: row 0 at the top of the image.
            let idx = (row * width + col) * 3;
            let cell = sample_at(&raster, row, col);
            let (r, g, b) = match cell {
                Some(s) => match s.kind {
                    SampleKind::Terrain => {
                        let v = (s.meters.unwrap_or(0.0) - min_e) / range;
                        let gray = (v * 255.0).clamp(0.0, 255.0) as u8;
                        (gray, gray, gray)
                    }
                    SampleKind::Sea => (30, 90, 200),
                    SampleKind::InlandWater => (60, 160, 210),
                    SampleKind::Seabed => (20, 60, 130),
                    SampleKind::InlandBottom => (15, 45, 100),
                    SampleKind::NoData => (255, 0, 255),
                },
                None => (0, 0, 0),
            };
            pixels[idx] = r;
            pixels[idx + 1] = g;
            pixels[idx + 2] = b;
        }
    }

    let file = std::fs::File::create(&args.output)?;
    let w = BufWriter::new(file);
    let mut encoder = png::Encoder::new(w, width as u32, height as u32);
    encoder.set_color(png::ColorType::Rgb);
    encoder.set_depth(png::BitDepth::Eight);
    let mut writer = encoder.write_header()?;
    writer.write_image_data(&pixels)?;

    println!(
        "rendered mesh {} ({}) -> {}  [{}x{}]",
        raster.mesh,
        raster.source,
        args.output.display(),
        width,
        height
    );
    Ok(())
}
