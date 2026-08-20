//! Small durable-file primitives. Format-specific serialization is deliberately
//! left to callers so storage does not become a configuration framework.

use std::{
    fs::{self, File, OpenOptions},
    io::{self, Write},
    path::{Path, PathBuf},
    sync::atomic::{AtomicU64, Ordering},
};
use thiserror::Error;

static TEMP_COUNTER: AtomicU64 = AtomicU64::new(1);

#[derive(Debug, Error)]
pub enum FileStoreError {
    #[error("path has no file name: {0:?}")]
    MissingFileName(PathBuf),
    #[error("{operation} {path:?}: {source}")]
    Io {
        operation: &'static str,
        path: PathBuf,
        #[source]
        source: io::Error,
    },
}

fn io_error(operation: &'static str, path: &Path, source: io::Error) -> FileStoreError {
    FileStoreError::Io {
        operation,
        path: path.to_path_buf(),
        source,
    }
}

fn temporary_path(path: &Path) -> Result<PathBuf, FileStoreError> {
    let name = path
        .file_name()
        .ok_or_else(|| FileStoreError::MissingFileName(path.to_path_buf()))?
        .to_string_lossy();
    let id = TEMP_COUNTER.fetch_add(1, Ordering::Relaxed);
    Ok(path.with_file_name(format!(".{name}.tmp-{}-{id}", std::process::id())))
}

struct TempGuard(PathBuf);

impl Drop for TempGuard {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.0);
    }
}

pub fn read(path: impl AsRef<Path>) -> Result<Vec<u8>, FileStoreError> {
    let path = path.as_ref();
    fs::read(path).map_err(|source| io_error("read", path, source))
}

/// Write through a same-directory temporary file, fsync it, atomically rename
/// it using the operating system's rename semantics, then fsync the parent on
/// Unix. Platforms that cannot atomically replace an existing destination
/// return the rename error rather than silently falling back to a non-atomic
/// delete-and-move sequence.
pub fn write_atomic(path: impl AsRef<Path>, bytes: &[u8]) -> Result<(), FileStoreError> {
    let path = path.as_ref();
    let parent = path.parent().filter(|p| !p.as_os_str().is_empty()).unwrap_or(Path::new("."));
    fs::create_dir_all(parent).map_err(|source| io_error("create parent", parent, source))?;

    let temp = temporary_path(path)?;
    let guard = TempGuard(temp.clone());
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&temp)
        .map_err(|source| io_error("create temporary file", &temp, source))?;
    file.write_all(bytes)
        .map_err(|source| io_error("write temporary file", &temp, source))?;
    file.sync_all()
        .map_err(|source| io_error("fsync temporary file", &temp, source))?;
    drop(file);

    fs::rename(&temp, path).map_err(|source| io_error("rename temporary file", path, source))?;
    std::mem::forget(guard);

    #[cfg(unix)]
    {
        let directory = File::open(parent).map_err(|source| io_error("open parent", parent, source))?;
        directory
            .sync_all()
            .map_err(|source| io_error("fsync parent", parent, source))?;
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn test_path(name: &str) -> PathBuf {
        std::env::temp_dir().join(format!(
            "audiagentic-file-store-{}-{name}",
            std::process::id()
        ))
    }

    #[test]
    fn writes_and_reads_new_file() {
        let directory = test_path("new");
        let path = directory.join("state.bin");
        let _ = fs::remove_dir_all(&directory);
        write_atomic(&path, b"state").unwrap();
        assert_eq!(read(&path).unwrap(), b"state");
        fs::remove_dir_all(directory).unwrap();
    }

    #[cfg(unix)]
    #[test]
    fn replaces_existing_file_atomically_on_unix() {
        let directory = test_path("replace");
        let path = directory.join("state.bin");
        let _ = fs::remove_dir_all(&directory);
        write_atomic(&path, b"one").unwrap();
        write_atomic(&path, b"two").unwrap();
        assert_eq!(read(&path).unwrap(), b"two");
        fs::remove_dir_all(directory).unwrap();
    }
}
