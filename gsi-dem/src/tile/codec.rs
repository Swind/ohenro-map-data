//! Elevation encoding + compression (plan §20/§22).
//!
//! float32 (normalized) -> int16 (1 m, `ELEV_NODATA` = i16::MIN) -> zstd.

use crate::gsi::error::{DemError, DemResult};
use crate::tile::grid::ELEV_NODATA;

/// Quantize a float elevation to int16 meters. NaN -> NODATA sentinel.
pub fn quantize(e: f32) -> i16 {
    if e.is_nan() {
        ELEV_NODATA
    } else {
        let v = e.round() as i64;
        v.clamp(i16::MIN as i64 + 1, i16::MAX as i64) as i16
    }
}

/// Dequantize int16 back to meters (NODATA -> None).
pub fn dequantize(e: i16) -> Option<f32> {
    if e == ELEV_NODATA {
        None
    } else {
        Some(e as f32)
    }
}

pub fn compress(data: &[u8]) -> DemResult<Vec<u8>> {
    zstd::bulk::compress(data, 10).map_err(|e| DemError::Parse {
        context: format!("zstd compress: {e}"),
    })
}

pub fn decompress(data: &[u8], capacity: usize) -> DemResult<Vec<u8>> {
    zstd::bulk::decompress(data, capacity).map_err(|e| DemError::Parse {
        context: format!("zstd decompress: {e}"),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn quantize_round_trip() {
        assert_eq!(quantize(123.4), 123);
        assert_eq!(quantize(123.6), 124);
        assert_eq!(quantize(-5.16), -5);
        assert_eq!(quantize(f32::NAN), ELEV_NODATA);
        assert_eq!(dequantize(quantize(123.4)), Some(123.0));
        assert_eq!(dequantize(ELEV_NODATA), None);
    }

    #[test]
    fn zstd_round_trip() {
        let raw: Vec<u8> = (0..65536u32).map(|i| (i % 251) as u8).collect();
        let comp = compress(&raw).unwrap();
        assert!(comp.len() < raw.len());
        let back = decompress(&comp, raw.len()).unwrap();
        assert_eq!(back, raw);
    }
}
