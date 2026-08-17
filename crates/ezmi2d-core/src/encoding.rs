use encoding_rs::{DecoderResult, SHIFT_JIS};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TextEncoding {
    Utf8,
    ShiftJis,
    HpRoman8,
}

impl TextEncoding {
    pub const fn name(self) -> &'static str {
        match self {
            Self::Utf8 => "utf-8",
            Self::ShiftJis => "shift_jis",
            Self::HpRoman8 => "hp-roman8",
        }
    }

    pub fn for_label(label: &str) -> Option<Self> {
        let normalized = label
            .chars()
            .filter(|character| !matches!(character, '-' | '_' | ' '))
            .flat_map(char::to_lowercase)
            .collect::<String>();
        match normalized.as_str() {
            "utf8" | "unicode" => Some(Self::Utf8),
            "sjis" | "shiftjis" | "cp932" | "windows31j" | "windows932" | "mskanji" => {
                Some(Self::ShiftJis)
            }
            "roman8" | "hproman8" | "r8" | "cp1051" | "ibm1051" => Some(Self::HpRoman8),
            _ => None,
        }
    }

    pub fn decode(self, bytes: &[u8]) -> Result<String, TextDecodeError> {
        match self {
            Self::Utf8 => std::str::from_utf8(bytes)
                .map(str::to_owned)
                .map_err(|error| TextDecodeError {
                    offset: error.valid_up_to(),
                    length: error.error_len().unwrap_or(1),
                }),
            Self::ShiftJis => decode_shift_jis(bytes),
            Self::HpRoman8 => decode_hp_roman8(bytes),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EncodingSource {
    Override,
    Utf8Bom,
    MiVersion,
    Declared,
    Heuristic,
    AsciiOnly,
    Undetermined,
}

impl EncodingSource {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Override => "override",
            Self::Utf8Bom => "utf8_bom",
            Self::MiVersion => "mi_version",
            Self::Declared => "declared",
            Self::Heuristic => "heuristic",
            Self::AsciiOnly => "ascii_only",
            Self::Undetermined => "undetermined",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct TextDecodeError {
    pub offset: usize,
    pub length: usize,
}

fn decode_shift_jis(bytes: &[u8]) -> Result<String, TextDecodeError> {
    let mut decoder = SHIFT_JIS.new_decoder_without_bom_handling();
    let capacity = decoder
        .max_utf8_buffer_length_without_replacement(bytes.len())
        .unwrap_or_else(|| bytes.len().saturating_mul(3).saturating_add(4));
    let mut output = String::with_capacity(capacity);
    let (result, read) = decoder.decode_to_string_without_replacement(bytes, &mut output, true);
    match result {
        DecoderResult::InputEmpty => Ok(output),
        DecoderResult::Malformed(length, consumed_after) => {
            let length = usize::from(length);
            let consumed_after = usize::from(consumed_after);
            Err(TextDecodeError {
                offset: read.saturating_sub(length + consumed_after),
                length,
            })
        }
        DecoderResult::OutputFull => unreachable!("decoder capacity was precomputed"),
    }
}

fn decode_hp_roman8(bytes: &[u8]) -> Result<String, TextDecodeError> {
    let mut output = String::with_capacity(bytes.len());
    for (offset, byte) in bytes.iter().copied().enumerate() {
        if byte == 0xff {
            return Err(TextDecodeError { offset, length: 1 });
        }
        if byte < 0xa0 {
            output.push(char::from(byte));
        } else {
            output.push(HP_ROMAN8_HIGH[usize::from(byte - 0xa0)]);
        }
    }
    Ok(output)
}

// Mapping for bytes A0 through FE from the HP Roman-8 character set.
const HP_ROMAN8_HIGH: [char; 95] = [
    '\u{00a0}', 'À', 'Â', 'È', 'Ê', 'Ë', 'Î', 'Ï', '´', 'ˋ', 'ˆ', '¨', '˜', 'Ù', 'Û', '₤', '¯',
    'Ý', 'ý', '°', 'Ç', 'ç', 'Ñ', 'ñ', '¡', '¿', '¤', '£', '¥', '§', 'ƒ', '¢', 'â', 'ê', 'ô', 'û',
    'á', 'é', 'ó', 'ú', 'à', 'è', 'ò', 'ù', 'ä', 'ë', 'ö', 'ü', 'Å', 'î', 'Ø', 'Æ', 'å', 'í', 'ø',
    'æ', 'Ä', 'ì', 'Ö', 'Ü', 'É', 'ï', 'ß', 'Ô', 'Á', 'Ã', 'ã', 'Ð', 'ð', 'Í', 'Ì', 'Ó', 'Ò', 'Õ',
    'õ', 'Š', 'š', 'Ú', 'Ÿ', 'ÿ', 'Þ', 'þ', '·', 'µ', '¶', '¾', '—', '¼', '½', 'ª', 'º', '«', '■',
    '»', '±',
];

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn decodes_windows_shift_jis_without_replacement() {
        assert_eq!(
            TextEncoding::ShiftJis.decode(b"\x83\\\x83A\x83\x89\x81[\x83f\x83b\x83N\x83X"),
            Ok("ソアラーデックス".to_owned())
        );
    }

    #[test]
    fn reports_the_first_malformed_shift_jis_byte() {
        assert_eq!(
            TextEncoding::ShiftJis.decode(b"ok\x81"),
            Err(TextDecodeError {
                offset: 2,
                length: 1,
            })
        );
    }

    #[test]
    fn supports_hp_roman8_and_its_undefined_byte() {
        assert_eq!(
            TextEncoding::HpRoman8.decode(b"caf\xc5"),
            Ok("café".to_owned())
        );
        assert_eq!(
            TextEncoding::HpRoman8.decode(b"a\xff"),
            Err(TextDecodeError {
                offset: 1,
                length: 1,
            })
        );
    }
}
