use std::fs::File;
use std::io::{BufReader, Cursor, Read};
use std::path::Path;
use zip::ZipArchive;

use crate::gsi::error::DemError;

/// Max size of an inner ZIP read into memory (plan §41).
pub const MAX_INNER_ZIP_SIZE: u64 = 64 * 1024 * 1024;

/// Open a ZIP archive from disk.
pub fn open_archive<P: AsRef<Path>>(path: P) -> Result<ZipArchive<BufReader<File>>, DemError> {
    let file = File::open(path.as_ref()).map_err(|e| DemError::Io {
        context: format!("open {}", path.as_ref().display()),
        source: e,
    })?;
    ZipArchive::new(BufReader::new(file)).map_err(|e| DemError::Zip {
        context: format!("read {}", path.as_ref().display()),
        source: e,
    })
}

/// Names of all entries that look like an XML document (case-insensitive `.xml`).
pub fn xml_entry_names<R: Read + std::io::Seek>(
    zip: &mut ZipArchive<R>,
) -> Result<Vec<String>, DemError> {
    let mut names = Vec::new();
    for i in 0..zip.len() {
        let entry = zip.by_index(i).map_err(|e| DemError::Zip {
            context: format!("list entry {i}"),
            source: e,
        })?;
        let name = entry.name().to_string();
        if name.to_ascii_lowercase().ends_with(".xml") {
            names.push(name);
        }
    }
    Ok(names)
}

/// Read a single XML entry as a streaming reader (no file on disk).
///
/// The entry is decompressed into an in-memory buffer (each DEM XML is
/// ~0.5-0.8 MB), then wrapped in a BufReader. The plan's "streaming"
/// constraint refers to not extracting XML to disk; a per-entry memory
/// buffer keeps the pipeline simple for Phase 1.
pub fn read_entry<R: Read + std::io::Seek>(
    zip: &mut ZipArchive<R>,
    name: &str,
) -> Result<BufReader<Cursor<Vec<u8>>>, DemError> {
    let bytes = read_entry_to_bytes(zip, name)?;
    Ok(BufReader::new(Cursor::new(bytes)))
}

/// Read an entry fully into memory.
pub fn read_entry_to_bytes<R: Read + std::io::Seek>(
    zip: &mut ZipArchive<R>,
    name: &str,
) -> Result<Vec<u8>, DemError> {
    let mut entry = zip.by_name(name).map_err(|e| DemError::Zip {
        context: format!("open entry {name}"),
        source: e,
    })?;
    let size = entry.size();
    if size > MAX_INNER_ZIP_SIZE {
        return Err(DemError::InnerZipTooLarge {
            name: name.to_string(),
            size,
            max: MAX_INNER_ZIP_SIZE,
        });
    }
    let mut buf = Vec::with_capacity(size as usize);
    entry.read_to_end(&mut buf).map_err(|e| DemError::Io {
        context: format!("read entry {name}"),
        source: e,
    })?;
    Ok(buf)
}

/// Open a nested ZIP from an in-memory buffer.
pub fn open_inner_zip(bytes: Vec<u8>) -> Result<ZipArchive<Cursor<Vec<u8>>>, DemError> {
    ZipArchive::new(Cursor::new(bytes)).map_err(|e| DemError::Zip {
        context: "open inner zip".to_string(),
        source: e,
    })
}
