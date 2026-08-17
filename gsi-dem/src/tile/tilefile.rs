//! On-disk tile file format (Phase 5 output / Phase 6 SQLite input).
//!
//! Layout: magic `G5T1`, layer u8 (5|10), tile_x u32, tile_y u32,
//! elev_len u32, zstd(elevation int16[65536] LE), source_len u32 = 65536,
//! source u8[65536].

use std::io::{BufReader, BufWriter, Read, Write};
use std::path::Path;

use crate::gsi::error::{DemError, DemResult};
use crate::tile::grid::TILE_SIZE;

pub const MAGIC: &[u8; 4] = b"G5T1";
pub const LAYER_DEM5: u8 = 5;
pub const LAYER_DEM10: u8 = 10;

#[derive(Debug, Clone)]
pub struct TileFile {
    pub layer: u8,
    pub tile_x: u32,
    pub tile_y: u32,
    /// zstd-compressed int16[65536] little-endian elevation.
    pub elevation_zstd: Vec<u8>,
    /// raw u8[65536] source codes.
    pub source: Vec<u8>,
}

impl TileFile {
    pub fn write(&self, path: &Path) -> DemResult<()> {
        let mut w = BufWriter::new(std::fs::File::create(path).map_err(|e| DemError::Io {
            context: format!("create {}", path.display()),
            source: e,
        })?);
        let io = |e: std::io::Error| DemError::Io {
            context: format!("write {}", path.display()),
            source: e,
        };
        w.write_all(MAGIC).map_err(io)?;
        w.write_all(&[self.layer]).map_err(io)?;
        w.write_all(&self.tile_x.to_le_bytes()).map_err(io)?;
        w.write_all(&self.tile_y.to_le_bytes()).map_err(io)?;
        w.write_all(&(self.elevation_zstd.len() as u32).to_le_bytes())
            .map_err(io)?;
        w.write_all(&self.elevation_zstd).map_err(io)?;
        w.write_all(&(self.source.len() as u32).to_le_bytes())
            .map_err(io)?;
        w.write_all(&self.source).map_err(io)?;
        w.flush().map_err(io)?;
        Ok(())
    }

    pub fn read(path: &Path) -> DemResult<TileFile> {
        let file = std::fs::File::open(path).map_err(|e| DemError::Io {
            context: format!("open {}", path.display()),
            source: e,
        })?;
        let mut r = BufReader::new(file);
        let io = |e: std::io::Error| DemError::Io {
            context: format!("read {}", path.display()),
            source: e,
        };
        let mut magic = [0u8; 4];
        r.read_exact(&mut magic).map_err(io)?;
        if &magic != MAGIC {
            return Err(DemError::Parse {
                context: format!("{}: not a G5T1 tile", path.display()),
            });
        }
        let mut layer = [0u8; 1];
        r.read_exact(&mut layer).map_err(io)?;
        let mut b4 = [0u8; 4];
        r.read_exact(&mut b4).map_err(io)?;
        let tile_x = u32::from_le_bytes(b4);
        r.read_exact(&mut b4).map_err(io)?;
        let tile_y = u32::from_le_bytes(b4);
        r.read_exact(&mut b4).map_err(io)?;
        let elev_len = u32::from_le_bytes(b4) as usize;
        let mut elevation_zstd = vec![0u8; elev_len];
        r.read_exact(&mut elevation_zstd).map_err(io)?;
        r.read_exact(&mut b4).map_err(io)?;
        let src_len = u32::from_le_bytes(b4) as usize;
        let mut source = vec![0u8; src_len];
        r.read_exact(&mut source).map_err(io)?;
        Ok(TileFile {
            layer: layer[0],
            tile_x,
            tile_y,
            elevation_zstd,
            source,
        })
    }

    /// Decompressed elevation grid (int16 LE), or an error if malformed.
    pub fn elevation_raw(&self) -> DemResult<Vec<i16>> {
        let raw = crate::tile::codec::decompress(&self.elevation_zstd, TILE_SIZE * TILE_SIZE * 2)?;
        if raw.len() != TILE_SIZE * TILE_SIZE * 2 {
            return Err(DemError::Parse {
                context: format!(
                    "tile {} {}: expected {} bytes, got {}",
                    self.tile_x,
                    self.tile_y,
                    TILE_SIZE * TILE_SIZE * 2,
                    raw.len()
                ),
            });
        }
        let mut out = Vec::with_capacity(TILE_SIZE * TILE_SIZE);
        for chunk in raw.chunks_exact(2) {
            out.push(i16::from_le_bytes([chunk[0], chunk[1]]));
        }
        Ok(out)
    }
}
