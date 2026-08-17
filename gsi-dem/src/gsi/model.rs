use serde::Serialize;
use std::fmt;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub enum DemSource {
    Dem5A,
    Dem5B,
    Dem5C,
    Dem10B,
}

impl DemSource {
    pub fn from_entry_name(name: &str) -> Option<DemSource> {
        let upper = name.to_ascii_uppercase();
        if upper.contains("DEM5A") {
            Some(DemSource::Dem5A)
        } else if upper.contains("DEM5B") {
            Some(DemSource::Dem5B)
        } else if upper.contains("DEM5C") {
            Some(DemSource::Dem5C)
        } else if upper.contains("DEM10B") {
            Some(DemSource::Dem10B)
        } else {
            None
        }
    }

    pub fn as_str(&self) -> &'static str {
        match self {
            DemSource::Dem5A => "DEM5A",
            DemSource::Dem5B => "DEM5B",
            DemSource::Dem5C => "DEM5C",
            DemSource::Dem10B => "DEM10B",
        }
    }

    /// Per-pixel source code for merged rasters (plan §16):
    /// 0 = NODATA, 1 = DEM10B, 2 = DEM5C, 3 = DEM5B, 4 = DEM5A.
    pub fn source_code(&self) -> u8 {
        match self {
            DemSource::Dem5A => 4,
            DemSource::Dem5B => 3,
            DemSource::Dem5C => 2,
            DemSource::Dem10B => 1,
        }
    }
}

impl fmt::Display for DemSource {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[repr(u8)]
pub enum SampleKind {
    NoData = 0,
    Terrain = 1,
    Sea = 2,
    InlandWater = 3,
    Seabed = 4,
    InlandBottom = 5,
}

impl SampleKind {
    pub fn as_str(&self) -> &'static str {
        match self {
            SampleKind::NoData => "nodata",
            SampleKind::Terrain => "terrain",
            SampleKind::Sea => "sea",
            SampleKind::InlandWater => "inland_water",
            SampleKind::Seabed => "seabed",
            SampleKind::InlandBottom => "inland_bottom",
        }
    }
}

/// A single parsed GSI DEM raster (one XML entry).
#[derive(Debug, Clone, Serialize)]
pub struct GsiDemRaster {
    pub entry_name: String,
    pub source: DemSource,

    pub fid: String,
    pub survey_date: String,
    pub type_label: String,
    pub mesh: String,
    pub crs: String,

    pub lower_lat: f64,
    pub lower_lon: f64,
    pub upper_lat: f64,
    pub upper_lon: f64,

    pub grid_low_x: u32,
    pub grid_low_y: u32,
    pub grid_high_x: u32,
    pub grid_high_y: u32,
    pub axis_labels: String,

    pub sequence_rule: String,
    pub sequence_order: String,
    pub start_x: u32,
    pub start_y: u32,

    /// elevation per sample in tuple order (NaN for nodata)
    pub elevation: Vec<f32>,
    /// mask per sample in tuple order
    pub mask: Vec<u8>,
}

impl GsiDemRaster {
    pub fn width(&self) -> usize {
        (self.grid_high_x - self.grid_low_x + 1) as usize
    }

    pub fn height(&self) -> usize {
        (self.grid_high_y - self.grid_low_y + 1) as usize
    }

    pub fn sample_count(&self) -> usize {
        self.elevation.len()
    }

    /// Full-grid capacity (width x height). Partial meshes store fewer samples.
    pub fn grid_capacity(&self) -> usize {
        self.width() * self.height()
    }

    pub fn is_partial(&self) -> bool {
        self.sample_count() != self.grid_capacity()
    }

    /// Count samples by kind.
    pub fn kind_counts(&self) -> [(SampleKind, usize); 6] {
        let mut counts = [0usize; 6];
        for &m in &self.mask {
            counts[m as usize] += 1;
        }
        [
            (SampleKind::NoData, counts[0]),
            (SampleKind::Terrain, counts[1]),
            (SampleKind::Sea, counts[2]),
            (SampleKind::InlandWater, counts[3]),
            (SampleKind::Seabed, counts[4]),
            (SampleKind::InlandBottom, counts[5]),
        ]
    }
}
