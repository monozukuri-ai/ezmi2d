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
            ensure_mi_text(&bytes, CompressionKind::Gzip)?;
            Ok(DecodedInput {
                bytes: Cow::Owned(bytes),
                compression: Some(CompressionKind::Gzip),
                container_size: data.len(),
            })
        }
        Some(CompressionKind::UnixCompress) => {
            let bytes = decode_unix_compress(data, options)?;
            ensure_mi_text(&bytes, CompressionKind::UnixCompress)?;
            Ok(DecodedInput {
                bytes: Cow::Owned(bytes),
                compression: Some(CompressionKind::UnixCompress),
                container_size: data.len(),
            })
        }
        Some(compression) => Err(MiError::UnsupportedCompression {
            compression: compression.as_str(),
        }),
    }
}

fn ensure_mi_text(bytes: &[u8], compression: CompressionKind) -> Result<(), MiError> {
    let not_mi = || MiError::InvalidCompressedStream {
        compression: compression.as_str(),
        message: "decompressed payload is not a recognized MI text stream".to_owned(),
    };
    let format = detect_format(bytes).map_err(|_| not_mi())?;
    if format.kind != MiFormatKind::Text || format.compression.is_some() {
        return Err(not_mi());
    }
    Ok(())
}

pub(crate) fn detect_compression(data: &[u8]) -> Option<CompressionKind> {
    if data.starts_with(&[0x1f, 0x8b]) {
        return Some(CompressionKind::Gzip);
    }
    if data.starts_with(&[0x1f, 0x9d]) {
        return Some(CompressionKind::UnixCompress);
    }
    if data.starts_with(&[0x1f, 0x1e]) {
        return Some(CompressionKind::UnixPack);
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

const UNIX_COMPRESS_HEADER_BYTES: usize = 3;
const LZW_INIT_BITS: u32 = 9;
const LZW_MAX_BITS_LIMIT: u32 = 16;
const LZW_CLEAR_CODE: usize = 256;

/// Decode a unix `compress`(1) `.Z` stream (ME10 installations commonly store
/// MI drawings this way). Mirrors the reference `ncompress` reader, including
/// its quirk of padding the bit stream to an `n_bits`-byte group boundary
/// whenever the code width grows or the table is cleared.
fn decode_unix_compress(data: &[u8], options: ScanOptions) -> Result<Vec<u8>, MiError> {
    let corrupt = |message: String| MiError::InvalidCompressedStream {
        compression: CompressionKind::UnixCompress.as_str(),
        message,
    };
    let Some(&flags) = data.get(UNIX_COMPRESS_HEADER_BYTES - 1) else {
        return Err(corrupt("stream ends before the flags byte".to_owned()));
    };
    let max_bits = u32::from(flags & 0x1f);
    let block_mode = flags & 0x80 != 0;
    if !(LZW_INIT_BITS..=LZW_MAX_BITS_LIMIT).contains(&max_bits) {
        return Err(corrupt(format!(
            "unsupported maximum code width {max_bits}"
        )));
    }

    let bytes = &data[UNIX_COMPRESS_HEADER_BYTES..];
    let total_bits = bytes.len().saturating_mul(8);
    let table_size = 1usize << max_bits;
    let mut prefixes = vec![0u16; table_size];
    let mut suffixes = vec![0u8; table_size];
    for (code, suffix) in suffixes.iter_mut().enumerate().take(256) {
        *suffix = code as u8;
    }

    let first_free = if block_mode { 257 } else { 256 };
    let mut free_ent = first_free;
    let mut n_bits = LZW_INIT_BITS;
    let mut maxcode = (1usize << n_bits) - 1;
    let mut bitmask = (1u32 << n_bits) - 1;
    let mut oldcode: Option<usize> = None;
    let mut finchar = 0u8;
    let mut posbits = 0usize;
    // compress(1) consumes its input in groups of `n_bits` bytes (8 codes) and
    // discards the rest of the current group on every width change or clear.
    // Group boundaries are therefore relative to the previous reset position.
    let mut group_base = 0usize;
    let permitted_by_ratio = data.len().saturating_mul(options.max_compression_ratio);
    let mut output = Vec::new();
    let mut stack = Vec::new();

    loop {
        if free_ent > maxcode {
            let group = (n_bits as usize) << 3;
            posbits = group_base + (posbits - group_base).div_ceil(group) * group;
            group_base = posbits;
            n_bits += 1;
            maxcode = if n_bits == max_bits {
                1usize << n_bits
            } else {
                (1usize << n_bits) - 1
            };
            bitmask = (1u32 << n_bits) - 1;
        }
        if posbits + n_bits as usize > total_bits {
            break;
        }
        let byte = posbits >> 3;
        let shift = posbits & 7;
        let mut window = 0u32;
        for (index, value) in bytes[byte..bytes.len().min(byte + 3)].iter().enumerate() {
            window |= u32::from(*value) << (8 * index);
        }
        let code = ((window >> shift) & bitmask) as usize;
        posbits += n_bits as usize;

        let Some(previous) = oldcode else {
            if code >= 256 {
                return Err(corrupt(format!("first code {code} is not a literal")));
            }
            finchar = code as u8;
            oldcode = Some(code);
            output.push(finchar);
            continue;
        };

        if code == LZW_CLEAR_CODE && block_mode {
            let group = (n_bits as usize) << 3;
            posbits = group_base + (posbits - group_base).div_ceil(group) * group;
            group_base = posbits;
            // ncompress keeps one dead slot here so the next stored entry
            // lands on 257 again, matching the encoder after a clear.
            free_ent = first_free - 1;
            n_bits = LZW_INIT_BITS;
            maxcode = (1usize << n_bits) - 1;
            bitmask = (1u32 << n_bits) - 1;
            continue;
        }

        let incode = code;
        let mut current = code;
        stack.clear();
        if current >= free_ent {
            if current > free_ent {
                return Err(corrupt(format!(
                    "code {current} references a table entry beyond {free_ent}"
                )));
            }
            // The KwKwK case: the code being defined by this very step.
            stack.push(finchar);
            current = previous;
        }
        while current >= 256 {
            stack.push(suffixes[current]);
            current = usize::from(prefixes[current]);
            if stack.len() > table_size {
                return Err(corrupt("prefix chain forms a cycle".to_owned()));
            }
        }
        finchar = suffixes[current];
        stack.push(finchar);

        let expanded_size = output.len().saturating_add(stack.len());
        check_limit(
            "decompressed bytes",
            expanded_size,
            options.max_decompressed_size,
        )?;
        if expanded_size > permitted_by_ratio {
            return Err(MiError::LimitExceeded {
                resource: "compression ratio",
                actual: expanded_size.div_ceil(data.len()),
                limit: options.max_compression_ratio,
            });
        }
        output.extend(stack.iter().rev());

        if free_ent < table_size {
            prefixes[free_ent] = previous as u16;
            suffixes[free_ent] = finchar;
            free_ent += 1;
        }
        oldcode = Some(incode);
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

    /// compress(1)-compatible test encoder. Mirrors the ncompress writer:
    /// block mode, codes packed LSB-first, and the output padded to a group
    /// boundary of `n_bits` bytes — relative to the previous reset — on every
    /// width change and clear. Verified against `gzip -dc` on generated
    /// streams and against real ME10 `.Z` archives.
    fn compress_z(data: &[u8], max_bits: u32, clear_at: Option<usize>) -> Vec<u8> {
        let mut body: Vec<u8> = Vec::new();
        let mut bitbuf = 0u32;
        let mut bitcnt = 0u32;
        let mut n_bits = 9u32;
        let mut base = 0usize;

        fn flush_group(
            body: &mut Vec<u8>,
            bitbuf: &mut u32,
            bitcnt: &mut u32,
            base: &mut usize,
            n_bits: u32,
        ) {
            while *bitcnt > 0 {
                body.push((*bitbuf & 0xff) as u8);
                *bitbuf >>= 8;
                *bitcnt = bitcnt.saturating_sub(8);
            }
            let group = n_bits as usize;
            while (body.len() - *base) % group != 0 {
                body.push(0);
            }
            *base = body.len();
        }

        fn emit(body: &mut Vec<u8>, bitbuf: &mut u32, bitcnt: &mut u32, n_bits: u32, code: usize) {
            *bitbuf |= (code as u32) << *bitcnt;
            *bitcnt += n_bits;
            while *bitcnt >= 8 {
                body.push((*bitbuf & 0xff) as u8);
                *bitbuf >>= 8;
                *bitcnt -= 8;
            }
        }

        let mut table: std::collections::HashMap<Vec<u8>, usize> =
            (0..256usize).map(|byte| (vec![byte as u8], byte)).collect();
        let mut free_ent = 257usize;
        let mut prefix: Vec<u8> = Vec::new();
        let mut emitted = 0usize;
        let mut clear_at = clear_at;
        for &byte in data {
            if clear_at == Some(emitted) && !prefix.is_empty() {
                emit(&mut body, &mut bitbuf, &mut bitcnt, n_bits, table[&prefix]);
                emitted += 1;
                emit(&mut body, &mut bitbuf, &mut bitcnt, n_bits, LZW_CLEAR_CODE);
                flush_group(&mut body, &mut bitbuf, &mut bitcnt, &mut base, n_bits);
                table = (0..256usize).map(|b| (vec![b as u8], b)).collect();
                free_ent = 257;
                n_bits = 9;
                prefix = vec![byte];
                clear_at = None;
                continue;
            }
            let mut candidate = prefix.clone();
            candidate.push(byte);
            if table.contains_key(&candidate) {
                prefix = candidate;
                continue;
            }
            emit(&mut body, &mut bitbuf, &mut bitcnt, n_bits, table[&prefix]);
            emitted += 1;
            if free_ent < (1usize << max_bits) {
                table.insert(candidate, free_ent);
                free_ent += 1;
                // The decoder stores entries one code late, so the width only
                // changes for the code after free_ent passes 2^n.
                if free_ent > (1usize << n_bits) && n_bits < max_bits {
                    flush_group(&mut body, &mut bitbuf, &mut bitcnt, &mut base, n_bits);
                    n_bits += 1;
                }
            }
            prefix = vec![byte];
        }
        if !prefix.is_empty() {
            emit(&mut body, &mut bitbuf, &mut bitcnt, n_bits, table[&prefix]);
        }
        while bitcnt > 0 {
            body.push((bitbuf & 0xff) as u8);
            bitbuf >>= 8;
            bitcnt = bitcnt.saturating_sub(8);
        }
        let mut out = vec![0x1f, 0x9d, 0x80 | max_bits as u8];
        out.extend(body);
        out
    }

    /// `compress_z(MINIMAL_MI, 16, None)`, pinned so the bit layout cannot
    /// silently drift from the compress(1) format.
    const MINIMAL_MI_Z: &[u8] = &[
        0x1f, 0x9d, 0x90, 0x23, 0xfc, 0xc8, 0x50, 0x30, 0x22, 0xa0, 0x1f, 0x05,
    ];

    #[test]
    fn decodes_the_pinned_unix_compress_fixture() {
        let decoded = decode_input(MINIMAL_MI_Z, ScanOptions::default()).unwrap();
        assert_eq!(decoded.bytes.as_ref(), MINIMAL_MI);
        assert_eq!(decoded.compression, Some(CompressionKind::UnixCompress));
        assert_eq!(decoded.container_size, MINIMAL_MI_Z.len());
        assert_eq!(compress_z(MINIMAL_MI, 16, None), MINIMAL_MI_Z);
    }

    #[test]
    fn round_trips_unix_compress_streams_across_width_changes_and_clears() {
        let mut growth = b"#~2\n".to_vec();
        for round in 0..12u32 {
            growth.extend((0..=255u8).map(|byte| byte.rotate_left(round)));
        }
        growth.extend_from_slice(b"\n##~~\n");
        let repetitive = [
            b"#~2\n".as_slice(),
            &b"ABCABCABCABC".repeat(40),
            b"\n##~~\n",
        ]
        .concat();

        for (label, plain, max_bits, clear_at) in [
            ("minimal", MINIMAL_MI.to_vec(), 16, None),
            ("growth", growth, 12, None),
            ("repetitive", repetitive.clone(), 16, None),
            ("with_clear", repetitive, 16, Some(20)),
        ] {
            let compressed = compress_z(&plain, max_bits, clear_at);
            let decoded = decode_input(&compressed, ScanOptions::default())
                .unwrap_or_else(|error| panic!("{label}: {error}"));
            assert_eq!(decoded.bytes.as_ref(), plain, "{label}");
            assert_eq!(decoded.compression, Some(CompressionKind::UnixCompress));
        }
    }

    #[test]
    fn enforces_limits_and_validity_on_unix_compress_streams() {
        let data = [b"#~2\n".as_slice(), &vec![b' '; 4096], b"\n##~~\n"].concat();
        let compressed = compress_z(&data, 16, None);

        assert!(matches!(
            decode_input(
                &compressed,
                ScanOptions {
                    max_decompressed_size: data.len() - 1,
                    ..ScanOptions::default()
                }
            ),
            Err(MiError::LimitExceeded {
                resource: "decompressed bytes",
                ..
            })
        ));
        assert!(matches!(
            decode_input(
                &compressed,
                ScanOptions {
                    max_compression_ratio: 1,
                    ..ScanOptions::default()
                }
            ),
            Err(MiError::LimitExceeded {
                resource: "compression ratio",
                ..
            })
        ));

        // Flags byte outside the 9..=16 code-width range used by compress(1).
        assert!(matches!(
            decode_input(&[0x1f, 0x9d, 0x88, 0x00], ScanOptions::default()),
            Err(MiError::InvalidCompressedStream { .. })
        ));
        // A valid stream whose payload is not MI text.
        assert!(matches!(
            decode_input(
                &compress_z(b"not an MI stream\n", 16, None),
                ScanOptions::default()
            ),
            Err(MiError::InvalidCompressedStream { .. })
        ));
    }
}
