use thiserror::Error;

/// Errors that prevent a bounded raw scan from completing.
#[derive(Debug, Error, Clone, PartialEq, Eq)]
pub enum MiError {
    #[error("input does not have a recognized MI text or compressed-stream signature")]
    InvalidFormat,

    #[error("input has a {compression} compressed-stream signature; decoding it is not supported")]
    UnsupportedCompression { compression: &'static str },

    #[error("invalid {compression} compressed MI stream: {message}")]
    InvalidCompressedStream {
        compression: &'static str,
        message: String,
    },

    #[error("unsupported MI text encoding: {encoding}")]
    UnsupportedTextEncoding { encoding: String },

    #[error("{resource} value {actual} exceeds configured limit {limit}")]
    LimitExceeded {
        resource: &'static str,
        actual: usize,
        limit: usize,
    },
}

impl MiError {
    pub fn is_limit_error(&self) -> bool {
        matches!(self, Self::LimitExceeded { .. })
    }

    pub fn is_unsupported_error(&self) -> bool {
        matches!(self, Self::UnsupportedCompression { .. })
    }

    pub fn is_encoding_error(&self) -> bool {
        matches!(self, Self::UnsupportedTextEncoding { .. })
    }
}
