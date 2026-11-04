//! Elevation encoding + compression (plan §20/§22).
//!
//! float32 (normalized) -> int16 (1 m, `ELEV_NODATA` = i16::MIN) -> zstd.
//!
//! GSI's raw rasters also carry a legacy no-data sentinel of `-9999`
//! (see `datasets/gsi/docs/gis-dem-converter.md`; DEM10B uses `その他,-9999.00`).
//! Real route packs shipped earlier databases that persisted that legacy
//! value in DEM5 cells, so the shared codec must treat it as no-data on
//! read and never re-emit it on write.

use crate::gsi::error::{DemError, DemResult};
use crate::tile::grid::ELEV_NODATA;

/// Legacy GSI no-data sentinel (`-9999`) that leaks into real databases from
/// source rasters. Treating it as a plausible negative elevation (as opposed
/// to no-data) silently corrupts fallback chains (a DEM5 cell reporting
/// `-9999 m` would shadow a valid DEM10 sample). Both directions of the codec
/// normalize this value to [`ELEV_NODATA`].
pub const LEGACY_ELEV_NODATA: i16 = -9999;

/// Quantize a float elevation to int16 meters. NaN -> NODATA sentinel.
///
/// The exact legacy GSI no-data value (`-9999.0`) is mapped to [`ELEV_NODATA`]
/// so newly written databases can never persist it. No real elevation on this
/// dataset is anywhere near `-9999 m`, so the mapping is unambiguous.
pub fn quantize(e: f32) -> i16 {
    if e.is_nan() {
        ELEV_NODATA
    } else {
        let v = e.round() as i64;
        if v == LEGACY_ELEV_NODATA as i64 {
            ELEV_NODATA
        } else {
            v.clamp(i16::MIN as i64 + 1, i16::MAX as i64) as i16
        }
    }
}

/// Dequantize int16 back to meters (NODATA -> None).
///
/// Treats both the canonical sentinel ([`ELEV_NODATA`]) and the legacy GSI
/// `-9999` as no-data so old databases remain correct on read.
pub fn dequantize(e: i16) -> Option<f32> {
    if e == ELEV_NODATA || e == LEGACY_ELEV_NODATA {
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
    fn dequantize_treats_legacy_9999_as_nodata() {
        assert_eq!(dequantize(LEGACY_ELEV_NODATA), None);
        assert_eq!(dequantize(ELEV_NODATA), None);
        // nearby plausible values still decode.
        assert_eq!(dequantize(-9998), Some(-9998.0));
        assert_eq!(dequantize(-10000), Some(-10000.0));
    }

    #[test]
    fn quantize_maps_exact_9999_to_nodata() {
        assert_eq!(quantize(-9999.0), ELEV_NODATA);
        // values that round to exactly -9999 also collapse to nodata so a
        // freshly written database can never persist the legacy sentinel.
        assert_eq!(quantize(-9999.4), ELEV_NODATA);
        // nearby values are left untouched.
        assert_eq!(quantize(-9998.4), -9998);
        assert_eq!(quantize(-10000.0), -10000);
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
