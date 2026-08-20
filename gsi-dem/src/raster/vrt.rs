//! Raw Int16 raster + GDAL VRT writer for the elevation visualization exporter.
//!
//! The exporter does not link libgdal. Rust writes a plain header-less
//! row-major signed-Int16-little-endian raster (`dem10.raw`) plus a small VRT
//! that describes it (`VRTRawRasterBand`). GeoTIFF conversion is delegated to
//! the GDAL CLI in the build pipeline.
//!
//! Raw layout (fixed by spec §6.5):
//! - row-major, no header.
//! - Every row is first filled with `ELEV_NODATA` so tiles missing from the
//!   database read back as NODATA, never as sparse-file zeros.
//! - Real tile rows are then seeked to their byte offset and written in place.
//! - All offsets use checked arithmetic.

use std::fs::File;
use std::io::{BufWriter, Seek, SeekFrom, Write};
use std::path::Path;

use crate::gsi::error::{DemError, DemResult};
use crate::tile::grid::ELEV_NODATA;

fn io_err(context: &str) -> impl FnOnce(std::io::Error) -> DemError {
    let context = context.to_string();
    move |source| DemError::Io { context, source }
}

/// Row-major writer for the header-less raw Int16 raster.
pub struct RawWriter {
    file: BufWriter<File>,
    tile_size: usize,
    row_bytes: usize,
    tile_row_bytes: usize,
}

impl RawWriter {
    /// Create the raw file, pre-filling every row with `ELEV_NODATA` so
    /// tiles missing from the database are explicitly NODATA, not zeros.
    pub fn create(path: &Path, width: usize, height: usize, tile_size: usize) -> DemResult<Self> {
        let row_bytes = width.checked_mul(2).ok_or_else(|| DemError::Parse {
            context: "row bytes overflow".into(),
        })?;
        let file = File::create(path).map_err(io_err(&format!("create {}", path.display())))?;
        let mut writer = BufWriter::with_capacity(1 << 20, file);

        let nodata_row = vec![ELEV_NODATA.to_le_bytes(); width];
        let mut nodata_row_flat: Vec<u8> = Vec::with_capacity(row_bytes);
        for b in &nodata_row {
            nodata_row_flat.extend_from_slice(b);
        }
        for _ in 0..height {
            writer
                .write_all(&nodata_row_flat)
                .map_err(io_err("write nodata row"))?;
        }
        writer.flush().map_err(io_err("flush nodata rows"))?;

        Ok(RawWriter {
            file: writer,
            tile_size,
            row_bytes,
            tile_row_bytes: tile_size.checked_mul(2).ok_or_else(|| DemError::Parse {
                context: "tile row bytes overflow".into(),
            })?,
        })
    }

    /// Overwrite one tile's 256 rows at their grid offsets.
    pub fn write_tile(&mut self, tile_x: i64, tile_y: i64, cells: &[i16]) -> DemResult<()> {
        let expected =
            self.tile_size
                .checked_mul(self.tile_size)
                .ok_or_else(|| DemError::Parse {
                    context: "tile cell count overflow".into(),
                })?;
        if cells.len() != expected {
            return Err(DemError::Parse {
                context: format!(
                    "write_tile({tile_x},{tile_y}): expected {expected} cells, got {}",
                    cells.len()
                ),
            });
        }
        let tile_x = usize::try_from(tile_x).map_err(|_| DemError::Parse {
            context: "negative tile_x".into(),
        })?;
        let tile_y = usize::try_from(tile_y).map_err(|_| DemError::Parse {
            context: "negative tile_y".into(),
        })?;
        let x_off = tile_x
            .checked_mul(self.tile_row_bytes)
            .ok_or_else(|| DemError::Parse {
                context: "x offset overflow".into(),
            })?;
        let tile_stride =
            self.tile_size
                .checked_mul(self.row_bytes)
                .ok_or_else(|| DemError::Parse {
                    context: "tile stride overflow".into(),
                })?;
        let y_off = tile_y
            .checked_mul(tile_stride)
            .ok_or_else(|| DemError::Parse {
                context: "y offset overflow".into(),
            })?;

        for row in 0..self.tile_size {
            let base = y_off
                .checked_add(row.checked_mul(self.row_bytes).unwrap())
                .and_then(|b| b.checked_add(x_off))
                .ok_or_else(|| DemError::Parse {
                    context: "row offset overflow".into(),
                })?;
            let start = row * self.tile_size;
            let mut bytes = Vec::with_capacity(self.tile_row_bytes);
            for cell in &cells[start..start + self.tile_size] {
                bytes.extend_from_slice(&cell.to_le_bytes());
            }
            self.file
                .seek(SeekFrom::Start(base as u64))
                .map_err(io_err("seek raw"))?;
            self.file
                .write_all(&bytes)
                .map_err(io_err("write tile row"))?;
        }
        Ok(())
    }

    /// Flush and finish the writer.
    pub fn finish(self) -> DemResult<()> {
        let mut file = self.file;
        file.flush().map_err(io_err("flush raw"))?;
        file.into_inner()
            .map_err(|e| DemError::Io {
                context: "sync raw".into(),
                source: e.into_error(),
            })?
            .sync_all()
            .map_err(io_err("sync raw"))?;
        Ok(())
    }
}

/// Minimal XML escaping for values placed inside element text / attributes.
fn xml_escape(s: &str) -> String {
    s.replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
        .replace('\'', "&apos;")
}

/// Write a `VRTRawRasterBand` VRT referencing the sibling raw file.
pub fn write_vrt(
    path: &Path,
    width: usize,
    height: usize,
    srs: &str,
    geo_transform: [f64; 6],
    raw_filename: &str,
) -> DemResult<()> {
    let line_offset = width.checked_mul(2).ok_or_else(|| DemError::Parse {
        context: "line offset overflow".into(),
    })?;
    let xml = format!(
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n\
         <VRTDataset rasterXSize=\"{width}\" rasterYSize=\"{height}\">\n\
         \x20 <SRS>{srs_esc}</SRS>\n\
         \x20 <GeoTransform>{west}, {lon_step}, 0, {north}, 0, {lat_step}</GeoTransform>\n\
         \x20 <VRTRasterBand dataType=\"Int16\" band=\"1\" subClass=\"VRTRawRasterBand\">\n\
         \x20   <NoDataValue>-32768</NoDataValue>\n\
         \x20   <SourceFilename relativeToVRT=\"1\">{raw}</SourceFilename>\n\
         \x20   <ImageOffset>0</ImageOffset>\n\
         \x20   <PixelOffset>2</PixelOffset>\n\
         \x20   <LineOffset>{line_offset}</LineOffset>\n\
         \x20   <ByteOrder>LSB</ByteOrder>\n\
         \x20 </VRTRasterBand>\n\
         </VRTDataset>\n",
        srs_esc = xml_escape(srs),
        raw = xml_escape(raw_filename),
        west = geo_transform[0],
        lon_step = geo_transform[1],
        north = geo_transform[3],
        lat_step = geo_transform[5],
    );
    std::fs::write(path, xml).map_err(io_err(&format!("write {}", path.display())))?;
    Ok(())
}
