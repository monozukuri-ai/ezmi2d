use std::borrow::Cow;
use std::io::Read;

use flate2::bufread::GzDecoder;

use crate::error::MiError;
use crate::options::ScanOptions;
use crate::raw::{CompressionKind, MiFormatKind};
use crate::scanner::detect_format;

const DECOMPRESSION_CHUNK_BYTES: usize = 64 * 1024;

/// Logical MI bytes prepared from an uncompressed input or a verified envelope.
#[derive(Debug)]
pub struct DecodedInput<'a> {
    pub bytes: Cow<'a, [u8]>,
    pub compression: Option<CompressionKind>,
    pub container_size: usize,
}

/// Decode a supported compressed MI envelope while applying bomb and truncation guards.
pub fn decode_input<'a>(data: &'a [u8], options: ScanOptions) -> Result<DecodedInput<'a>, MiError> {
    check_limit("input bytes", data.len(), options.max_file_size)?;

    match detect_compression(data) {
        None => Ok(DecodedInput {
            bytes: Cow::Borrowed(data),
            compression: None,
            container_size: data.len(),
        }),
        Some(CompressionKind::Gzip) => {
            let bytes = decode_gzip(data, options)?;
            let format = detect_format(&bytes).map_err(|_| MiError::InvalidCompressedStream {
                compression: CompressionKind::Gzip.as_str(),
                message: "decompressed payload is not a recognized MI text stream".to_owned(),
            })?;
            if format.kind != MiFormatKind::Text || format.compression.is_some() {
                return Err(MiError::InvalidCompressedStream {
                    compression: CompressionKind::Gzip.as_str(),
                    message: "decompressed payload is not a recognized MI text stream".to_owned(),
                });
            }
            Ok(DecodedInput {
                bytes: Cow::Owned(bytes),
                compression: Some(CompressionKind::Gzip),
                container_size: data.len(),
            })
        }
        Some(compression) => Err(MiError::UnsupportedCompression {
            compression: compression.as_str(),
        }),
    }
}

pub(crate) fn detect_compression(data: &[u8]) -> Option<CompressionKind> {
    if data.starts_with(&[0x1f, 0x8b]) {
        return Some(CompressionKind::Gzip);
    }
    if data.starts_with(b"PK\x03\x04")
        || data.starts_with(b"PK\x05\x06")
        || data.starts_with(b"PK\x07\x08")
    {
        return Some(CompressionKind::Zip);
    }
    if data.len() >= 2 {
        let cmf = data[0];
        let flg = data[1];
        let header = u16::from(cmf) << 8 | u16::from(flg);
        if cmf & 0x0f == 8 && cmf >> 4 <= 7 && header % 31 == 0 {
            return Some(CompressionKind::Zlib);
        }
    }
    None
}

fn decode_gzip(data: &[u8], options: ScanOptions) -> Result<Vec<u8>, MiError> {
    let initial_capacity = data
        .len()
        .saturating_mul(4)
        .min(options.max_decompressed_size)
        .min(8 * 1024 * 1024);
    let mut output = Vec::with_capacity(initial_capacity);
    let mut decoder = GzDecoder::new(data);
    let mut chunk = [0u8; DECOMPRESSION_CHUNK_BYTES];

    loop {
        let count = decoder
            .read(&mut chunk)
            .map_err(|error| MiError::InvalidCompressedStream {
                compression: CompressionKind::Gzip.as_str(),
                message: error.to_string(),
            })?;
        if count == 0 {
            break;
        }

        let expanded_size = output.len().saturating_add(count);
        check_limit(
            "decompressed bytes",
            expanded_size,
            options.max_decompressed_size,
        )?;
        let permitted_by_ratio = data.len().saturating_mul(options.max_compression_ratio);
        if expanded_size > permitted_by_ratio {
            return Err(MiError::LimitExceeded {
                resource: "compression ratio",
                actual: expanded_size.div_ceil(data.len()),
                limit: options.max_compression_ratio,
            });
        }
        output.extend_from_slice(&chunk[..count]);
    }

    if !decoder.into_inner().is_empty() {
        return Err(MiError::InvalidCompressedStream {
            compression: CompressionKind::Gzip.as_str(),
            message: "trailing data or additional gzip members are not supported".to_owned(),
        });
    }
    Ok(output)
}

fn check_limit(resource: &'static str, actual: usize, limit: usize) -> Result<(), MiError> {
    if actual > limit {
        return Err(MiError::LimitExceeded {
            resource,
            actual,
            limit,
        });
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use std::io::Write;

    use flate2::write::GzEncoder;
    use flate2::Compression;

    use super::*;

    const MINIMAL_MI: &[u8] = b"#~2\n##~~\n";

    fn gzip(data: &[u8]) -> Vec<u8> {
        let mut encoder = GzEncoder::new(Vec::new(), Compression::default());
        encoder.write_all(data).unwrap();
        encoder.finish().unwrap()
    }

    #[test]
    fn decodes_one_gzip_member_and_retains_container_metadata() {
        let compressed = gzip(MINIMAL_MI);
        let decoded = decode_input(&compressed, ScanOptions::default()).unwrap();

        assert_eq!(decoded.bytes.as_ref(), MINIMAL_MI);
        assert_eq!(decoded.compression, Some(CompressionKind::Gzip));
        assert_eq!(decoded.container_size, compressed.len());
    }

    #[test]
    fn enforces_expanded_size_and_ratio_limits() {
        let data = [b"#~2\n".as_slice(), &vec![b' '; 4096], b"\n##~~\n"].concat();
        let compressed = gzip(&data);

        let expanded_limit = ScanOptions {
            max_decompressed_size: data.len() - 1,
            ..ScanOptions::default()
        };
        assert!(matches!(
            decode_input(&compressed, expanded_limit),
            Err(MiError::LimitExceeded {
                resource: "decompressed bytes",
                ..
            })
        ));

        let ratio_limit = ScanOptions {
            max_compression_ratio: 1,
            ..ScanOptions::default()
        };
        assert!(matches!(
            decode_input(&compressed, ratio_limit),
            Err(MiError::LimitExceeded {
                resource: "compression ratio",
                ..
            })
        ));
    }

    #[test]
    fn rejects_truncated_corrupt_and_concatenated_gzip_streams() {
        let compressed = gzip(MINIMAL_MI);
        assert!(matches!(
            decode_input(&compressed[..compressed.len() - 4], ScanOptions::default()),
            Err(MiError::InvalidCompressedStream { .. })
        ));

        let mut corrupt = compressed.clone();
        *corrupt.last_mut().unwrap() ^= 0xff;
        assert!(matches!(
            decode_input(&corrupt, ScanOptions::default()),
            Err(MiError::InvalidCompressedStream { .. })
        ));

        let concatenated = [compressed.as_slice(), gzip(MINIMAL_MI).as_slice()].concat();
        assert!(matches!(
            decode_input(&concatenated, ScanOptions::default()),
            Err(MiError::InvalidCompressedStream { .. })
        ));
    }

    #[test]
    fn rejects_a_valid_gzip_stream_whose_payload_is_not_mi() {
        assert!(matches!(
            decode_input(&gzip(b"not an MI stream\n"), ScanOptions::default()),
            Err(MiError::InvalidCompressedStream { .. })
        ));
    }
}
