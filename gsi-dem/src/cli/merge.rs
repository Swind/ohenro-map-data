use std::collections::BTreeMap;
use std::io::BufWriter;
use std::path::{Path, PathBuf};

use clap::Args;
use serde::Serialize;

use crate::gsi::archive;
use crate::gsi::model::DemSource;
use crate::gsi::xml::parse_dem;
use crate::raster::dem10::{dem10_elevation, dem10_fill_count};
use crate::raster::merged::{
    MergedMesh, SOURCE_DEM5A, SOURCE_DEM5B, SOURCE_DEM5C, SOURCE_NODATA, merge_rasters,
};

/// Merge DEM5A > DEM5B > DEM5C per mesh (pixel-level priority), and measure
/// how much of the leftover nodata is covered by the DEM10B fallback layer.
///
/// Archives are grouped by their 6-digit primary-mesh prefix (each archive
/// contains only meshes of its own region — verified over all 22,682 XML
/// entries), so each archive is decompressed exactly once and a region's
/// rasters are merged in memory before moving on.
#[derive(Debug, Args)]
pub struct MergeArgs {
    /// Root directory scanned recursively for DEM5 zip archives.
    #[arg(long, default_value = "source/GSI/DEM5")]
    pub input: PathBuf,

    /// Directory scanned recursively for DEM10B zip archives
    /// (one archive per region). Skipped if the path does not exist.
    #[arg(long, default_value = "source/GSI/DEM10B")]
    pub dem10b_input: PathBuf,

    /// Write merged per-mesh rasters as binary files into this directory.
    #[arg(long)]
    pub out_dir: Option<PathBuf>,

    /// Write the merge report (JSON) to this path.
    #[arg(long)]
    pub report: Option<PathBuf>,

    /// Render one merged mesh to a PNG (requires --render-output).
    #[arg(long)]
    pub render_mesh: Option<String>,

    /// Output path for the rendered merged mesh.
    #[arg(long)]
    pub render_output: Option<PathBuf>,

    /// Only process meshes in these primary regions (6-digit prefixes, repeatable).
    #[arg(long = "region")]
    pub regions: Vec<String>,

    /// Print the DEM5 + DEM10B fallback elevation for a point (lat lon).
    #[arg(long)]
    pub query_lat: Option<f64>,

    /// Print the DEM5 + DEM10B fallback elevation for a point (lat lon).
    #[arg(long)]
    pub query_lon: Option<f64>,
}

#[derive(Debug, Clone, Copy, Default, Serialize)]
struct MeshWins {
    a: usize,
    b: usize,
    c: usize,
    nodata: usize,
    dem10_fills: usize,
    remains: usize,
}

#[derive(Debug, Serialize)]
struct MeshRow {
    mesh: String,
    width: usize,
    height: usize,
    sources: Vec<String>,
    wins: MeshWins,
}

#[derive(Debug, Serialize, Default)]
struct Report {
    input: String,
    archives: BTreeMap<String, usize>,
    mesh_count: usize,
    mesh_combos: BTreeMap<String, usize>,
    pixels: MeshWins,
    meshes: Vec<MeshRow>,
    #[serde(skip)]
    query_answered: bool,
}

pub fn run(args: &MergeArgs) -> anyhow::Result<()> {
    let mut archives_by_region: BTreeMap<String, Vec<(DemSource, PathBuf)>> = BTreeMap::new();
    collect_archives(&args.input, &mut archives_by_region)?;

    let include =
        |region: &str| args.regions.is_empty() || args.regions.iter().any(|r| r == region);

    for region in &args.regions {
        if !archives_by_region.contains_key(region) {
            println!(
                "WARN: requested region {region} not found under {}",
                args.input.display()
            );
        }
    }

    let mut report = Report {
        input: args.input.display().to_string(),
        ..Default::default()
    };

    // DEM10B layer: one archive per region (independent 10m resolution).
    let mut dem10_by_region: BTreeMap<String, PathBuf> = BTreeMap::new();
    if args.dem10b_input.exists() {
        collect_dem10(&args.dem10b_input, &mut dem10_by_region)?;
        for _ in &dem10_by_region {
            *report.archives.entry("DEM10B".to_string()).or_insert(0) += 1;
        }
    } else {
        println!(
            "WARN: --dem10b-input {} does not exist — skipping DEM10B fallback layer",
            args.dem10b_input.display()
        );
    }

    let query = match (args.query_lat, args.query_lon) {
        (Some(lat), Some(lon)) => Some((lat, lon)),
        _ => None,
    };

    let mut rendered = 0usize;
    for (region, archives) in &archives_by_region {
        if !include(region) {
            continue;
        }
        for (src, _) in archives {
            *report.archives.entry(src.as_str().to_string()).or_insert(0) += 1;
        }
        merge_region(
            region,
            archives,
            dem10_by_region.get(region),
            query,
            args,
            &mut report,
            &mut rendered,
        )?;
    }

    if let (Some((lat, lon)), false) = (query, report.query_answered) {
        println!("WARN: query point ({lat}, {lon}) not inside any processed region");
    }

    let combos = combo_counts(&report.meshes);
    report.mesh_combos = combos;

    print_summary(&report);
    if let Some(path) = &args.report {
        write_json_report(path, &report)?;
        println!("report written to {}", path.display());
    }
    if args.render_mesh.is_some() && rendered == 0 {
        println!(
            "WARN: render_mesh {} not found among merged meshes",
            args.render_mesh.as_deref().unwrap_or("-")
        );
    }
    Ok(())
}

fn collect_archives(
    dir: &Path,
    out: &mut BTreeMap<String, Vec<(DemSource, PathBuf)>>,
) -> anyhow::Result<()> {
    let mut stack = vec![dir.to_path_buf()];
    while let Some(d) = stack.pop() {
        for entry in std::fs::read_dir(&d)? {
            let entry = entry?;
            let p = entry.path();
            if p.is_dir() {
                stack.push(p);
            } else if p.extension().is_some_and(|e| e == "zip") {
                let fname = p
                    .file_name()
                    .unwrap_or_default()
                    .to_string_lossy()
                    .into_owned();
                let Some(src) = DemSource::from_entry_name(&fname) else {
                    continue; // not a DEM5/10 archive we care about
                };
                if src == DemSource::Dem10B {
                    continue; // DEM10B fallback is Phase 4
                }
                let Some(region) = primary_prefix(&fname) else {
                    anyhow::bail!("cannot extract primary-mesh prefix from {}", p.display());
                };
                out.entry(region).or_default().push((src, p));
            }
        }
    }
    Ok(())
}

/// Extract the 6-digit primary mesh prefix from an archive name
/// (e.g. `FG-GML-513440-DEM5B-20080331.zip` -> `513440`).
fn primary_prefix(name: &str) -> Option<String> {
    let digits: String = name
        .chars()
        .filter(|c| c.is_ascii_digit())
        .take(6)
        .collect();
    (digits.len() == 6).then_some(digits)
}

/// Collect DEM10B archives (one per region) into `region -> path`.
fn collect_dem10(dir: &Path, out: &mut BTreeMap<String, PathBuf>) -> anyhow::Result<()> {
    let mut stack = vec![dir.to_path_buf()];
    while let Some(d) = stack.pop() {
        for entry in std::fs::read_dir(&d)? {
            let entry = entry?;
            let p = entry.path();
            if p.is_dir() {
                stack.push(p);
            } else if p.extension().is_some_and(|e| e == "zip") {
                let fname = p
                    .file_name()
                    .unwrap_or_default()
                    .to_string_lossy()
                    .into_owned();
                if DemSource::from_entry_name(&fname) != Some(DemSource::Dem10B) {
                    continue;
                }
                let Some(region) = primary_prefix(&fname) else {
                    anyhow::bail!("cannot extract primary-mesh prefix from {}", p.display());
                };
                if out.insert(region.clone(), p).is_some() {
                    anyhow::bail!("duplicate DEM10B archive for region {region}");
                }
            }
        }
    }
    Ok(())
}

fn merge_region(
    region: &str,
    archives: &[(DemSource, PathBuf)],
    dem10_path: Option<&PathBuf>,
    query: Option<(f64, f64)>,
    args: &MergeArgs,
    report: &mut Report,
    rendered: &mut usize,
) -> anyhow::Result<()> {
    // mesh -> (source, raster)
    let mut rasters: BTreeMap<String, Vec<(DemSource, crate::gsi::model::GsiDemRaster)>> =
        BTreeMap::new();

    for (src, path) in archives {
        let mut zip = archive::open_archive(path)?;
        let names = archive::xml_entry_names(&mut zip)?;
        for name in &names {
            let reader = archive::read_entry(&mut zip, name)?;
            let raster = parse_dem(name, reader)?;
            if &raster.mesh[..6] != region {
                anyhow::bail!(
                    "{} contains mesh {} outside its primary region {}",
                    path.display(),
                    raster.mesh,
                    region
                );
            }
            if rasters
                .get(&raster.mesh)
                .is_some_and(|v| v.iter().any(|(s, _)| s == src))
            {
                anyhow::bail!(
                    "duplicate {src} raster for mesh {} in {}",
                    raster.mesh,
                    path.display()
                );
            }
            rasters
                .entry(raster.mesh.clone())
                .or_default()
                .push((*src, raster));
        }
        println!(
            "  parsed {} ({}) — {} rasters",
            path.display(),
            src,
            names.len()
        );
    }

    // DEM10B fallback raster for this region (independent 10m layer).
    let mut dem10: Option<crate::gsi::model::GsiDemRaster> = None;
    if let Some(dem10_path) = dem10_path {
        let mut zip = archive::open_archive(dem10_path)?;
        let names = archive::xml_entry_names(&mut zip)?;
        for name in &names {
            let reader = archive::read_entry(&mut zip, name)?;
            dem10 = Some(parse_dem(name, reader)?);
        }
        if let Some(d) = &dem10 {
            println!(
                "  parsed {} (DEM10B) — {} raster(s)",
                dem10_path.display(),
                names.len()
            );
            if &d.mesh[..6] != region {
                anyhow::bail!(
                    "DEM10B {} covers mesh {} outside region {}",
                    dem10_path.display(),
                    d.mesh,
                    region
                );
            }
        }
    }

    for (mesh, sources) in &rasters {
        let refs: Vec<(&DemSource, &crate::gsi::model::GsiDemRaster)> =
            sources.iter().map(|(s, r)| (s, r)).collect();
        let merged = merge_rasters(mesh, &refs)?;

        let counts = merged.source_counts();
        let (dem10_fills, remains) = match &dem10 {
            Some(d) => dem10_fill_count(&merged, d),
            None => (0, 0),
        };
        let wins = MeshWins {
            a: counts[SOURCE_DEM5A as usize],
            b: counts[SOURCE_DEM5B as usize],
            c: counts[SOURCE_DEM5C as usize],
            nodata: counts[SOURCE_NODATA as usize],
            dem10_fills,
            remains,
        };
        report.pixels.a += wins.a;
        report.pixels.b += wins.b;
        report.pixels.c += wins.c;
        report.pixels.nodata += wins.nodata;
        report.pixels.dem10_fills += wins.dem10_fills;
        report.pixels.remains += wins.remains;
        report.mesh_count += 1;

        let src_labels: Vec<String> = sources
            .iter()
            .map(|(s, _)| s.as_str().to_string())
            .collect();
        report.meshes.push(MeshRow {
            mesh: mesh.clone(),
            width: merged.width,
            height: merged.height,
            sources: src_labels,
            wins,
        });

        if let Some((qlat, qlon)) = query.filter(|&(qlat, qlon)| merged.bounds.contains(qlat, qlon))
        {
            let (row, col) = merged.nearest_cell(qlat, qlon).unwrap();
            let s = merged.sample_at(row, col);
            let dem5_desc = match &s {
                Some(s) if s.meters.is_some() => format!(
                    "{:.2} m (kind={}, source={})",
                    s.meters.unwrap(),
                    s.kind.as_str(),
                    match s.source_code {
                        2 => "DEM5C",
                        3 => "DEM5B",
                        4 => "DEM5A",
                        _ => "nodata",
                    }
                ),
                _ => "no data".to_string(),
            };
            let dem10_desc = match &dem10 {
                Some(d) => dem10_elevation(d, qlat, qlon)
                    .map(|e| format!("{e:.2} m"))
                    .unwrap_or_else(|| "no data".to_string()),
                None => "no DEM10B layer".to_string(),
            };
            println!(
                "query ({qlat:.6}, {qlon:.6}) mesh={mesh}: DEM5={dem5_desc} | DEM10B fallback={dem10_desc}"
            );
            report.query_answered = true;
        }

        if let Some(out_dir) = &args.out_dir {
            std::fs::create_dir_all(out_dir)?;
            merged.write_bin(&out_dir.join(format!("{mesh}.bin")))?;
        }
        if args.render_mesh.as_deref() == Some(mesh) {
            let out = args
                .render_output
                .clone()
                .ok_or_else(|| anyhow::anyhow!("--render-mesh requires --render-output"))?;
            render_merged(&merged, &out)?;
            *rendered += 1;
        }
    }
    Ok(())
}

fn render_merged(merged: &MergedMesh, path: &Path) -> anyhow::Result<()> {
    let width = merged.width;
    let height = merged.height;
    let mut pixels = vec![0u8; width * height * 3];

    let mut min_e = f32::INFINITY;
    let mut max_e = f32::NEG_INFINITY;
    for &e in &merged.elevation {
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
            let i = (row * width + col) * 3;
            let s = merged.sample_at(row, col);
            let (r, g, b) = match s {
                Some(s) => match s.kind {
                    crate::gsi::model::SampleKind::Terrain => {
                        let v = (s.meters.unwrap_or(0.0) - min_e) / range;
                        let gray = (v * 255.0).clamp(0.0, 255.0) as u8;
                        (gray, gray, gray)
                    }
                    crate::gsi::model::SampleKind::Sea => (30, 90, 200),
                    crate::gsi::model::SampleKind::InlandWater => (60, 160, 210),
                    crate::gsi::model::SampleKind::Seabed => (20, 60, 130),
                    crate::gsi::model::SampleKind::InlandBottom => (15, 45, 100),
                    crate::gsi::model::SampleKind::NoData => (255, 0, 255),
                },
                None => (0, 0, 0),
            };
            pixels[i] = r;
            pixels[i + 1] = g;
            pixels[i + 2] = b;
        }
    }

    let file = std::fs::File::create(path)?;
    let w = BufWriter::new(file);
    let mut encoder = png::Encoder::new(w, width as u32, height as u32);
    encoder.set_color(png::ColorType::Rgb);
    encoder.set_depth(png::BitDepth::Eight);
    let mut writer = encoder.write_header()?;
    writer.write_image_data(&pixels)?;
    Ok(())
}

fn combo_counts(rows: &[MeshRow]) -> BTreeMap<String, usize> {
    let mut m = BTreeMap::new();
    for r in rows {
        let mut key = String::new();
        if r.sources.iter().any(|s| s == "DEM5A") {
            key.push('A');
        }
        if r.sources.iter().any(|s| s == "DEM5B") {
            key.push('B');
        }
        if r.sources.iter().any(|s| s == "DEM5C") {
            key.push('C');
        }
        *m.entry(if key.is_empty() { "-".to_string() } else { key })
            .or_insert(0) += 1;
    }
    m
}

fn print_summary(r: &Report) {
    println!();
    println!("=== DEM5 merge summary ===");
    println!(
        "archives: {}",
        r.archives
            .iter()
            .map(|(k, v)| format!("{k}={v}"))
            .collect::<Vec<_>>()
            .join(", ")
    );
    println!("meshes:   {}", r.mesh_count);
    if !r.mesh_combos.is_empty() {
        println!(
            "combos:   {}",
            r.mesh_combos
                .iter()
                .map(|(k, v)| format!("{k}={v}"))
                .collect::<Vec<_>>()
                .join(" ")
        );
    }
    println!(
        "pixels:   A={} B={} C={} nodata={}",
        r.pixels.a, r.pixels.b, r.pixels.c, r.pixels.nodata
    );
    if r.pixels.dem10_fills > 0 || r.pixels.remains > 0 {
        let fill_pct = if r.pixels.nodata > 0 {
            100.0 * r.pixels.dem10_fills as f64 / r.pixels.nodata as f64
        } else {
            0.0
        };
        println!(
            "dem10:    fills={} remains={} ({fill_pct:.1}% of DEM5 nodata covered)",
            r.pixels.dem10_fills, r.pixels.remains
        );
    }
}

fn write_json_report(path: &Path, r: &Report) -> anyhow::Result<()> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let file = std::fs::File::create(path)?;
    serde_json::to_writer_pretty(BufWriter::new(file), r)?;
    Ok(())
}
