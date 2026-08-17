use thiserror::Error;

#[derive(Debug, Error)]
pub enum DemError {
    #[error("io: {context}: {source}")]
    Io {
        context: String,
        #[source]
        source: std::io::Error,
    },

    #[error("zip: {context}: {source}")]
    Zip {
        context: String,
        #[source]
        source: zip::result::ZipError,
    },

    #[error("xml: {context}")]
    Xml { context: String },

    #[error("inner zip too large: {name} ({size} bytes > max {max})")]
    InnerZipTooLarge {
        name: String,
        size: u64,
        max: u64,
    },

    #[error("parse: {context}")]
    Parse { context: String },

    #[error("unsupported: {context}")]
    Unsupported { context: String },

    #[error("sqlite: {context}: {source}")]
    Db {
        context: String,
        #[source]
        source: rusqlite::Error,
    },
}

pub type DemResult<T> = Result<T, DemError>;