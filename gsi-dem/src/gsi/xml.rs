use std::io::BufRead;

use quick_xml::events::Event;
use quick_xml::Reader;

use crate::gsi::error::{DemError, DemResult};
use crate::gsi::model::{GsiDemRaster, SampleKind};

/// Streaming SAX-style parse of one GSI DEM GML XML entry.
///
/// Never builds a DOM. Only keeps the fields it needs, and parses the
/// tupleList into SoA arrays (elevation + mask).
pub fn parse_dem<R: BufRead>(name: &str, reader: R) -> DemResult<GsiDemRaster> {
    let mut parser = DemParser::new(name);
    parser.run(reader)?;
    parser.finish()
}

struct DemParser {
    entry_name: String,
    fid: String,
    survey_date: String,
    type_label: String,
    mesh: String,
    crs: String,

    lower_lat: f64,
    lower_lon: f64,
    upper_lat: f64,
    upper_lon: f64,

    grid_low_x: u32,
    grid_low_y: u32,
    grid_high_x: u32,
    grid_high_y: u32,
    axis_labels: String,

    sequence_rule: String,
    sequence_order: String,
    start_x: u32,
    start_y: u32,

    elevation: Vec<f32>,
    mask: Vec<u8>,

    // parser state
    in_tuple_list: bool,
    tuple_buf: Vec<u8>,
    // current simple-element text accumulation
    cur_text: Vec<u8>,
    // which simple element we're inside (by local name)
    in_field: Option<Field>,
}

#[derive(Clone, Copy, PartialEq)]
enum Field {
    Fid,
    LfSpanFr,
    DevDate,
    Type,
    Mesh,
    LowerCorner,
    UpperCorner,
    Low,
    High,
    AxisLabels,
    SequenceRule,
    StartPoint,
}

impl DemParser {
    fn new(entry_name: &str) -> Self {
        DemParser {
            entry_name: entry_name.to_string(),
            fid: String::new(),
            survey_date: String::new(),
            type_label: String::new(),
            mesh: String::new(),
            crs: String::new(),
            lower_lat: f64::NAN,
            lower_lon: f64::NAN,
            upper_lat: f64::NAN,
            upper_lon: f64::NAN,
            grid_low_x: 0,
            grid_low_y: 0,
            grid_high_x: 0,
            grid_high_y: 0,
            axis_labels: String::new(),
            sequence_rule: String::new(),
            sequence_order: String::new(),
            start_x: 0,
            start_y: 0,
            elevation: Vec::new(),
            mask: Vec::new(),
            in_tuple_list: false,
            tuple_buf: Vec::new(),
            cur_text: Vec::new(),
            in_field: None,
        }
    }

    fn run<R: BufRead>(&mut self, reader: R) -> DemResult<()> {
        let mut reader = Reader::from_reader(reader);
        reader.config_mut().trim_text(false);
        let mut buf = Vec::new();

        loop {
            buf.clear();
            match reader.read_event_into(&mut buf) {
                Ok(Event::Start(e)) => self.on_start(&e)?,
                Ok(Event::Empty(e)) => self.on_start(&e)?,
                Ok(Event::End(e)) => self.on_end(&e)?,
                Ok(Event::Text(t)) => self.on_text(t.as_ref()),
                Ok(Event::Eof) => break,
                Ok(_) => {}
                Err(e) => {
                    return Err(DemError::Xml {
                        context: format!("{}: {e}", self.entry_name),
                    })
                }
            }
        }
        Ok(())
    }

    fn local_name(e: &quick_xml::events::BytesStart) -> Vec<u8> {
        let name = e.name();
        let bytes = name.as_ref();
        match bytes.iter().position(|&b| b == b':') {
            Some(i) => bytes[i + 1..].to_vec(),
            None => bytes.to_vec(),
        }
    }

    fn on_start(&mut self, e: &quick_xml::events::BytesStart) -> DemResult<()> {
        let name = DemParser::local_name(e);

        match name.as_slice() {
            b"fid" => self.in_field = Some(Field::Fid),
            b"lfSpanFr" => self.in_field = Some(Field::LfSpanFr),
            b"devDate" => self.in_field = Some(Field::DevDate),
            b"type" => self.in_field = Some(Field::Type),
            b"mesh" => self.in_field = Some(Field::Mesh),
            b"lowerCorner" => self.in_field = Some(Field::LowerCorner),
            b"upperCorner" => self.in_field = Some(Field::UpperCorner),
            b"low" => self.in_field = Some(Field::Low),
            b"high" => self.in_field = Some(Field::High),
            b"axisLabels" => self.in_field = Some(Field::AxisLabels),
            b"sequenceRule" => {
                // capture sequenceRule order attribute
                for attr in e.attributes().flatten() {
                    if attr.key.as_ref() == b"order" {
                        self.sequence_order =
                            String::from_utf8_lossy(&attr.value).into_owned();
                    }
                }
                self.in_field = Some(Field::SequenceRule);
            }
            b"startPoint" => self.in_field = Some(Field::StartPoint),
            b"Envelope" => {
                // grab srsName from the gml:Envelope
                for attr in e.attributes().flatten() {
                    if attr.key.as_ref() == b"srsName" {
                        self.crs = String::from_utf8_lossy(&attr.value).into_owned();
                    }
                }
            }
            b"tupleList" => {
                self.in_tuple_list = true;
                self.tuple_buf.clear();
            }
            _ => {}
        }
        Ok(())
    }

    fn on_end(&mut self, e: &quick_xml::events::BytesEnd) -> DemResult<()> {
        let name = e.name();
        let bytes = name.as_ref();
        let local: Vec<u8> = match bytes.iter().position(|&b| b == b':') {
            Some(i) => bytes[i + 1..].to_vec(),
            None => bytes.to_vec(),
        };

        // flush pending text for simple fields
        let text = String::from_utf8_lossy(&self.cur_text).trim().to_string();
        if let Some(f) = self.in_field {
            match f {
                Field::Fid => self.fid = text,
                Field::LfSpanFr | Field::DevDate => {
                    if self.survey_date.is_empty() {
                        self.survey_date = text;
                    }
                }
                Field::Type => self.type_label = text,
                Field::Mesh => self.mesh = text,
                Field::LowerCorner => {
                    let (lat, lon) = parse_two(text.as_str());
                    self.lower_lat = lat;
                    self.lower_lon = lon;
                }
                Field::UpperCorner => {
                    let (lat, lon) = parse_two(text.as_str());
                    self.upper_lat = lat;
                    self.upper_lon = lon;
                }
                Field::Low => {
                    let (x, y) = parse_two(text.as_str());
                    self.grid_low_x = x as u32;
                    self.grid_low_y = y as u32;
                }
                Field::High => {
                    let (x, y) = parse_two(text.as_str());
                    self.grid_high_x = x as u32;
                    self.grid_high_y = y as u32;
                }
                Field::AxisLabels => self.axis_labels = text,
                Field::SequenceRule => self.sequence_rule = text,
                Field::StartPoint => {
                    let (x, y) = parse_two(text.as_str());
                    self.start_x = x as u32;
                    self.start_y = y as u32;
                }
            }
            self.in_field = None;
        }
        self.cur_text.clear();

        if local == b"tupleList" {
            self.in_tuple_list = false;
            self.finish_tuple_buf()
        } else {
            Ok(())
        }
    }

    fn on_text(&mut self, text: &[u8]) {
        if self.in_tuple_list {
            self.tuple_buf.extend_from_slice(text);
        } else if self.in_field.is_some() {
            self.cur_text.extend_from_slice(text);
        }
    }

    fn finish_tuple_buf(&mut self) -> DemResult<()> {
        let s = String::from_utf8_lossy(&self.tuple_buf);
        for line in s.split('\n') {
            let line = line.trim();
            if line.is_empty() {
                continue;
            }
            let (label, value) = split_tuple(line)?;
            let kind = classify_tuple(label, value)?;
            match kind {
                SampleKind::Terrain | SampleKind::InlandWater => {
                    let v = parse_elevation(value)?;
                    self.elevation.push(v);
                    self.mask.push(kind as u8);
                }
                SampleKind::Sea => {
                    self.elevation.push(0.0);
                    self.mask.push(SampleKind::Sea as u8);
                }
                SampleKind::NoData => {
                    self.elevation.push(f32::NAN);
                    self.mask.push(SampleKind::NoData as u8);
                }
            }
        }
        Ok(())
    }

    fn finish(self) -> DemResult<GsiDemRaster> {
        let raster = GsiDemRaster {
            entry_name: self.entry_name.clone(),
            source: crate::gsi::model::DemSource::from_entry_name(&self.entry_name)
                .ok_or_else(|| DemError::Unsupported {
                    context: format!("cannot determine source from entry name {}", self.entry_name),
                })?,
            fid: self.fid,
            survey_date: self.survey_date,
            type_label: self.type_label,
            mesh: self.mesh,
            crs: self.crs,
            lower_lat: self.lower_lat,
            lower_lon: self.lower_lon,
            upper_lat: self.upper_lat,
            upper_lon: self.upper_lon,
            grid_low_x: self.grid_low_x,
            grid_low_y: self.grid_low_y,
            grid_high_x: self.grid_high_x,
            grid_high_y: self.grid_high_y,
            axis_labels: self.axis_labels,
            sequence_rule: self.sequence_rule,
            sequence_order: self.sequence_order,
            start_x: self.start_x,
            start_y: self.start_y,
            elevation: self.elevation,
            mask: self.mask,
        };
        Ok(raster)
    }
}

fn parse_two(s: &str) -> (f64, f64) {
    let mut parts = s.split_whitespace();
    let a = parts.next().and_then(|p| p.parse().ok()).unwrap_or(0.0);
    let b = parts.next().and_then(|p| p.parse().ok()).unwrap_or(0.0);
    (a, b)
}

fn parse_elevation(s: &str) -> DemResult<f32> {
    s.trim()
        .trim_end_matches('.')
        .parse::<f32>()
        .map_err(|_| DemError::Parse {
            context: format!("invalid elevation value {s:?}"),
        })
}

fn split_tuple(line: &str) -> DemResult<(&str, &str)> {
    match line.split_once(',') {
        Some((a, b)) => Ok((a, b)),
        None => Err(DemError::Parse {
            context: format!("invalid tuple line {line:?}"),
        }),
    }
}

/// Classify a tuple line into a SampleKind.
///
/// DEM5 files (地表面/海水面/内水面/データなし) carry an explicit semantic
/// label. DEM10B files use a single label `その他` where `-9999.00` is the
/// nodata/sea sentinel and any other value is terrain elevation.
fn classify_tuple(label: &str, value: &str) -> DemResult<SampleKind> {
    match label {
        "地表面" => Ok(SampleKind::Terrain),
        "海水面" => Ok(SampleKind::Sea),
        "内水面" => Ok(SampleKind::InlandWater),
        "データなし" => Ok(SampleKind::NoData),
        "その他" => {
            let v = value.trim().trim_end_matches('.');
            if v == "-9999" || v == "-9999.00" {
                Ok(SampleKind::NoData)
            } else {
                Ok(SampleKind::Terrain)
            }
        }
        other => Err(DemError::Unsupported {
            context: format!("unknown tuple kind {other:?}"),
        }),
    }
}