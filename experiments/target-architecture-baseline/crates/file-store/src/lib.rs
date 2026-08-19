#![forbid(unsafe_code)]

use std::fs;
use std::io::{self, Write};
use std::path::{Path, PathBuf};

use atomic_write_file::AtomicWriteFile;
use serde::Serialize;
use serde::de::DeserializeOwned;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum FileStoreError {
    #[error("file operation failed for {path}: {source}")]
    Io {
        path: PathBuf,
        #[source]
        source: io::Error,
    },
    #[error("invalid JSON in {path}: {source}")]
    InvalidJson {
        path: PathBuf,
        #[source]
        source: serde_json::Error,
    },
    #[error("could not serialize JSON for {path}: {source}")]
    SerializeJson {
        path: PathBuf,
        #[source]
        source: serde_json::Error,
    },
}

pub fn read_text(path: impl AsRef<Path>) -> Result<Option<String>, FileStoreError> {
    let path = path.as_ref();
    match fs::read_to_string(path) {
        Ok(value) => Ok(Some(value)),
        Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(None),
        Err(source) => Err(FileStoreError::Io {
            path: path.to_owned(),
            source,
        }),
    }
}

/// Missing is `Ok(None)`; malformed content is an error. Absence and corruption
/// are intentionally never conflated.
pub fn read_json<T: DeserializeOwned>(path: impl AsRef<Path>) -> Result<Option<T>, FileStoreError> {
    let path = path.as_ref();
    let Some(text) = read_text(path)? else {
        return Ok(None);
    };
    serde_json::from_str(&text)
        .map(Some)
        .map_err(|source| FileStoreError::InvalidJson {
            path: path.to_owned(),
            source,
        })
}

pub fn atomic_write_text(
    path: impl AsRef<Path>,
    content: impl AsRef<[u8]>,
) -> Result<(), FileStoreError> {
    let path = path.as_ref();
    if let Some(parent) = path.parent()
        && !parent.as_os_str().is_empty()
    {
        fs::create_dir_all(parent).map_err(|source| FileStoreError::Io {
            path: parent.to_owned(),
            source,
        })?;
    }

    let mut file = AtomicWriteFile::options()
        .open(path)
        .map_err(|source| FileStoreError::Io {
            path: path.to_owned(),
            source,
        })?;
    file.write_all(content.as_ref())
        .map_err(|source| FileStoreError::Io {
            path: path.to_owned(),
            source,
        })?;
    file.commit().map_err(|source| FileStoreError::Io {
        path: path.to_owned(),
        source,
    })
}

pub fn atomic_write_json<T: Serialize>(
    path: impl AsRef<Path>,
    value: &T,
) -> Result<(), FileStoreError> {
    let path = path.as_ref();
    let bytes =
        serde_json::to_vec_pretty(value).map_err(|source| FileStoreError::SerializeJson {
            path: path.to_owned(),
            source,
        })?;
    atomic_write_text(path, bytes)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde::{Deserialize, Serialize};
    use std::time::{SystemTime, UNIX_EPOCH};

    #[derive(Debug, Deserialize, Eq, PartialEq, Serialize)]
    struct State {
        value: u32,
    }

    fn test_dir(label: &str) -> PathBuf {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        std::env::temp_dir().join(format!(
            "audiagentic-file-store-{label}-{}-{nonce}",
            std::process::id()
        ))
    }

    #[test]
    fn atomic_json_round_trip_and_replace() {
        let dir = test_dir("replace");
        let path = dir.join("nested/state.json");
        atomic_write_json(&path, &State { value: 1 }).unwrap();
        atomic_write_json(&path, &State { value: 2 }).unwrap();
        assert_eq!(read_json::<State>(&path).unwrap(), Some(State { value: 2 }));
        fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn missing_and_malformed_are_not_conflated() {
        let dir = test_dir("malformed");
        let missing = dir.join("missing.json");
        assert_eq!(read_json::<State>(&missing).unwrap(), None);

        let malformed = dir.join("bad.json");
        atomic_write_text(&malformed, b"{ definitely-not-json").unwrap();
        assert!(matches!(
            read_json::<State>(&malformed),
            Err(FileStoreError::InvalidJson { .. })
        ));
        fs::remove_dir_all(dir).unwrap();
    }
}
