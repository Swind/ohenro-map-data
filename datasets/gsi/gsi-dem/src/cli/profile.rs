use std::collections::BTreeMap;
use std::fs::File;
use std::io::{BufReader, BufWriter};
use std::path::PathBuf;

use clap::Args;
use serde::Serialize;
use serde_json::Value;

use crate::db::ElevationDb;

/// Build elevation profiles for GeoJSON LineString route features.
#[derive(Debug, Args)]
pub struct ProfileArgs {
    /// Path to the SQLite elevation database.
    pub db: PathBuf,

    /// Input GeoJSON FeatureCollection with LineString features.
    #[arg(long)]
    pub input: PathBuf,

    /// Output profile JSON.
    #[arg(long)]
    pub output: PathBuf,

    /// Distance between profile samples in meters.
    #[arg(long, default_value_t = 20.0)]
    pub interval_m: f64,
}

#[derive(Serialize)]
struct ProfileDocument {
    schema_version: u8,
    sampling: SamplingInfo,
    routes: Vec<RouteProfile>,
}

#[derive(Serialize)]
struct SamplingInfo {
    method: &'static str,
    interval_m: f64,
}

#[derive(Serialize)]
struct RouteProfile {
    route_id: String,
    segments: Vec<SegmentProfile>,
}

#[derive(Serialize)]
struct SegmentProfile {
    segment_id: String,
    distance_m: f64,
    elevation_min_m: Option<f32>,
    elevation_max_m: Option<f32>,
    ascent_m: f32,
    descent_m: f32,
    missing_distance_m: f64,
    samples: Vec<ProfileSample>,
}

#[derive(Serialize)]
struct ProfileSample {
    distance_m: f64,
    lon: f64,
    lat: f64,
    elevation_m: Option<f32>,
    layer: Option<u8>,
    source_code: Option<u8>,
}

pub fn run(args: &ProfileArgs) -> anyhow::Result<()> {
    if !args.interval_m.is_finite() || args.interval_m <= 0.0 {
        return Err(anyhow::anyhow!(
            "--interval-m must be a positive finite number"
        ));
    }
    let input: Value = serde_json::from_reader(BufReader::new(File::open(&args.input)?))?;
    let profiles = build_profiles(&input, &args.db, args.interval_m)?;
    serde_json::to_writer_pretty(BufWriter::new(File::create(&args.output)?), &profiles)?;
    println!("profile: wrote {} routes", profiles.routes.len());
    Ok(())
}

fn build_profiles(
    input: &Value,
    db_path: &std::path::Path,
    interval_m: f64,
) -> anyhow::Result<ProfileDocument> {
    let features = input
        .get("features")
        .and_then(Value::as_array)
        .ok_or_else(|| anyhow::anyhow!("input must be a GeoJSON FeatureCollection"))?;
    let mut db = ElevationDb::open(db_path)?;
    let mut routes: BTreeMap<String, Vec<SegmentProfile>> = BTreeMap::new();
    for (feature_index, feature) in features.iter().enumerate() {
        let properties = feature
            .get("properties")
            .and_then(Value::as_object)
            .ok_or_else(|| {
                anyhow::anyhow!(
                    "feature {}: properties must be an object",
                    feature_index + 1
                )
            })?;
        let route_id = properties
            .get("route_id")
            .and_then(Value::as_str)
            .ok_or_else(|| {
                anyhow::anyhow!(
                    "feature {}: properties.route_id is required",
                    feature_index + 1
                )
            })?;
        let segment_id = properties
            .get("segment_id")
            .and_then(Value::as_str)
            .map(str::to_owned)
            .unwrap_or_else(|| format!("{route_id}_L{:03}", feature_index + 1));
        if feature.pointer("/geometry/type").and_then(Value::as_str) != Some("LineString") {
            return Err(anyhow::anyhow!(
                "feature {}: geometry must be a LineString",
                feature_index + 1
            ));
        }
        let coordinates = feature
            .pointer("/geometry/coordinates")
            .and_then(Value::as_array)
            .ok_or_else(|| {
                anyhow::anyhow!(
                    "feature {}: geometry must be a LineString",
                    feature_index + 1
                )
            })?;
        let line = coordinates
            .iter()
            .enumerate()
            .map(|(i, position)| {
                let values = position.as_array().ok_or_else(|| {
                    anyhow::anyhow!(
                        "feature {} coordinate {}: expected [lon, lat]",
                        feature_index + 1,
                        i + 1
                    )
                })?;
                let lon = values
                    .first()
                    .and_then(Value::as_f64)
                    .filter(|v| v.is_finite())
                    .ok_or_else(|| {
                        anyhow::anyhow!(
                            "feature {} coordinate {}: invalid longitude",
                            feature_index + 1,
                            i + 1
                        )
                    })?;
                let lat = values
                    .get(1)
                    .and_then(Value::as_f64)
                    .filter(|v| v.is_finite())
                    .ok_or_else(|| {
                        anyhow::anyhow!(
                            "feature {} coordinate {}: invalid latitude",
                            feature_index + 1,
                            i + 1
                        )
                    })?;
                if !(-180.0..=180.0).contains(&lon) || !(-90.0..=90.0).contains(&lat) {
                    return Err(anyhow::anyhow!(
                        "feature {} coordinate {}: out of range",
                        feature_index + 1,
                        i + 1
                    ));
                }
                Ok((lon, lat))
            })
            .collect::<anyhow::Result<Vec<_>>>()?;
        if line.len() < 2 {
            return Err(anyhow::anyhow!(
                "feature {}: LineString needs at least two coordinates",
                feature_index + 1
            ));
        }
        let points = resample(&line, interval_m);
        let samples = db.sample_many(points.iter().map(|p| (p.2, p.1)))?;
        routes
            .entry(route_id.to_owned())
            .or_default()
            .push(segment_profile(segment_id, points, samples));
    }
    Ok(ProfileDocument {
        schema_version: 1,
        sampling: SamplingInfo {
            method: "nearest_cell",
            interval_m,
        },
        routes: routes
            .into_iter()
            .map(|(route_id, segments)| RouteProfile { route_id, segments })
            .collect(),
    })
}

fn segment_profile(
    segment_id: String,
    points: Vec<(f64, f64, f64)>,
    samples: Vec<crate::db::ElevationSample>,
) -> SegmentProfile {
    let mut min: Option<f32> = None;
    let mut max: Option<f32> = None;
    let mut ascent = 0.0;
    let mut descent = 0.0;
    let mut missing = 0.0;
    let mut previous: Option<(f64, Option<f32>)> = None;
    let samples = points
        .into_iter()
        .zip(samples)
        .map(|((distance_m, lon, lat), sample)| {
            if let Some(elevation) = sample.meters {
                min = Some(min.map_or(elevation, |v| v.min(elevation)));
                max = Some(max.map_or(elevation, |v| v.max(elevation)));
            }
            if let Some((previous_distance, previous_elevation)) = previous {
                if previous_elevation.is_none() || sample.meters.is_none() {
                    missing += distance_m - previous_distance;
                } else {
                    let difference = sample.meters.unwrap() - previous_elevation.unwrap();
                    if difference > 0.0 {
                        ascent += difference;
                    } else {
                        descent -= difference;
                    }
                }
            }
            previous = Some((distance_m, sample.meters));
            ProfileSample {
                distance_m,
                lon,
                lat,
                elevation_m: sample.meters,
                layer: sample.layer,
                source_code: sample.source_code,
            }
        })
        .collect();
    SegmentProfile {
        segment_id,
        distance_m: previous.map(|p| p.0).unwrap_or(0.0),
        elevation_min_m: min,
        elevation_max_m: max,
        ascent_m: ascent,
        descent_m: descent,
        missing_distance_m: missing,
        samples,
    }
}

fn resample(line: &[(f64, f64)], interval_m: f64) -> Vec<(f64, f64, f64)> {
    let mut output = vec![(0.0, line[0].0, line[0].1)];
    let mut total = 0.0;
    let mut next = interval_m;
    for pair in line.windows(2) {
        let length = haversine_m(pair[0], pair[1]);
        while length > 0.0 && next <= total + length {
            let fraction = (next - total) / length;
            output.push((
                next,
                pair[0].0 + (pair[1].0 - pair[0].0) * fraction,
                pair[0].1 + (pair[1].1 - pair[0].1) * fraction,
            ));
            next += interval_m;
        }
        total += length;
    }
    if output.last().is_none_or(|point| point.0 < total) {
        let end = line[line.len() - 1];
        output.push((total, end.0, end.1));
    }
    output
}

fn haversine_m(a: (f64, f64), b: (f64, f64)) -> f64 {
    let lat1 = a.1.to_radians();
    let lat2 = b.1.to_radians();
    let dlat = lat2 - lat1;
    let dlon = (b.0 - a.0).to_radians();
    let h = (dlat / 2.0).sin().powi(2) + lat1.cos() * lat2.cos() * (dlon / 2.0).sin().powi(2);
    6_371_000.0 * 2.0 * h.sqrt().atan2((1.0 - h).sqrt())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn resampling_preserves_endpoints() {
        let line = [(134.0, 34.0), (134.001, 34.0)];
        let samples = resample(&line, 20.0);
        assert_eq!(samples.first().unwrap().0, 0.0);
        assert!((samples.last().unwrap().1 - 134.001).abs() < 1e-12);
        assert!(samples.len() > 2);
    }
}
