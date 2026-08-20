//! Stable public error identity without a universal platform error type.
//!
//! Capability/domain crates keep their own typed Rust errors. Errors that cross
//! an application/capability boundary may implement `CodedError` to expose one
//! stable code, canonical message, and operator resolution per semantic failure.
//! This crate owns no registry, logger, transport envelope, or runtime loader.

use std::fmt;

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct ErrorCode(&'static str);

impl ErrorCode {
    /// Construct a compile-time validated AUDiaGentic error code.
    ///
    /// Codes use a known category prefix, one or more uppercase component
    /// segments, and a three-digit number, for example `CON-EVENT-001`.
    pub const fn new(value: &'static str) -> Self {
        if !valid_error_code(value) {
            panic!("invalid AUDiaGentic error code");
        }
        Self(value)
    }

    pub const fn as_str(self) -> &'static str {
        self.0
    }
}

impl fmt::Display for ErrorCode {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.0)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ErrorDefinition {
    code: ErrorCode,
    message: &'static str,
    resolution: &'static str,
}

impl ErrorDefinition {
    pub const fn new(code: ErrorCode, message: &'static str, resolution: &'static str) -> Self {
        if message.as_bytes().is_empty() {
            panic!("error message must not be empty");
        }
        if resolution.as_bytes().is_empty() {
            panic!("error resolution must not be empty");
        }
        Self {
            code,
            message,
            resolution,
        }
    }

    pub const fn code(self) -> ErrorCode {
        self.code
    }

    pub const fn message(self) -> &'static str {
        self.message
    }

    pub const fn resolution(self) -> &'static str {
        self.resolution
    }
}

/// Optional boundary identity for a domain-owned typed error.
///
/// This trait is intentionally not a base error type and does not require
/// serialization, logging, global registration, or a particular error crate.
pub trait CodedError {
    fn definition(&self) -> &'static ErrorDefinition;

    fn code(&self) -> ErrorCode {
        self.definition().code()
    }

    fn canonical_message(&self) -> &'static str {
        self.definition().message()
    }

    fn resolution(&self) -> &'static str {
        self.definition().resolution()
    }
}

const fn valid_error_code(value: &str) -> bool {
    let bytes = value.as_bytes();
    let len = bytes.len();
    if len < 8 {
        return false;
    }

    let mut prefix_end = 0;
    while prefix_end < len && bytes[prefix_end] != b'-' {
        prefix_end += 1;
    }
    if prefix_end == 0 || prefix_end >= len || !known_prefix(bytes, prefix_end) {
        return false;
    }

    // Final segment must be exactly three digits preceded by a hyphen.
    if len < prefix_end + 6 || bytes[len - 4] != b'-' {
        return false;
    }
    if !is_digit(bytes[len - 3]) || !is_digit(bytes[len - 2]) || !is_digit(bytes[len - 1]) {
        return false;
    }

    let component_start = prefix_end + 1;
    let component_end = len - 4;
    if component_start >= component_end {
        return false;
    }

    let mut index = component_start;
    let mut previous_hyphen = true;
    while index < component_end {
        let byte = bytes[index];
        if byte == b'-' {
            if previous_hyphen {
                return false;
            }
            previous_hyphen = true;
        } else if is_upper(byte) || is_digit(byte) {
            previous_hyphen = false;
        } else {
            return false;
        }
        index += 1;
    }
    !previous_hyphen
}

const fn known_prefix(bytes: &[u8], len: usize) -> bool {
    if len == 2 {
        return (bytes[0] == b'I' && bytes[1] == b'O') || (bytes[0] == b'T' && bytes[1] == b'O');
    }
    if len != 3 {
        return false;
    }

    (bytes[0] == b'V' && bytes[1] == b'A' && bytes[2] == b'L')
        || (bytes[0] == b'C' && bytes[1] == b'O' && bytes[2] == b'N')
        || (bytes[0] == b'R' && bytes[1] == b'E' && bytes[2] == b'S')
        || (bytes[0] == b'N' && bytes[1] == b'E' && bytes[2] == b'T')
        || (bytes[0] == b'E' && bytes[1] == b'X' && bytes[2] == b'T')
        || (bytes[0] == b'C' && bytes[1] == b'F' && bytes[2] == b'G')
        || (bytes[0] == b'V' && bytes[1] == b'E' && bytes[2] == b'R')
        || (bytes[0] == b'I' && bytes[1] == b'N' && bytes[2] == b'T')
        || (bytes[0] == b'U' && bytes[1] == b'N' && bytes[2] == b'S')
}

const fn is_upper(byte: u8) -> bool {
    byte >= b'A' && byte <= b'Z'
}

const fn is_digit(byte: u8) -> bool {
    byte >= b'0' && byte <= b'9'
}

#[cfg(test)]
mod tests {
    use super::*;

    const VALID: ErrorDefinition = ErrorDefinition::new(
        ErrorCode::new("CON-EVENT-001"),
        "Event cursor has expired.",
        "Restart from an available cursor.",
    );

    #[test]
    fn definitions_keep_one_stable_code_message_and_resolution() {
        assert_eq!(VALID.code().as_str(), "CON-EVENT-001");
        assert_eq!(VALID.message(), "Event cursor has expired.");
        assert_eq!(VALID.resolution(), "Restart from an available cursor.");
    }

    #[test]
    fn accepted_code_shape_supports_component_segments() {
        assert!(valid_error_code("VAL-CONFIG-001"));
        assert!(valid_error_code("EXT-HOST-PROC-042"));
        assert!(valid_error_code("IO-FILESTORE-999"));
    }

    #[test]
    fn invalid_code_shapes_are_rejected() {
        assert!(!valid_error_code("BAD-EVENT-001"));
        assert!(!valid_error_code("CON-event-001"));
        assert!(!valid_error_code("CON--EVENT-001"));
        assert!(!valid_error_code("CON-EVENT-01"));
    }
}
