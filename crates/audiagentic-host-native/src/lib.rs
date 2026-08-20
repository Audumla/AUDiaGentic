//! Native host-facility implementations.
//!
//! This crate implements concrete operating-system behavior behind the narrow
//! contracts in `audiagentic-host`. It does not aggregate facilities into a
//! global host object.

use std::{
    fs, io,
    path::{Path, PathBuf},
};

use audiagentic_file_store::{FileStoreError, read as read_file, write_atomic};
use audiagentic_host::{FileHost, FileReadAuthority, FileWriteAuthority};
use thiserror::Error;

#[derive(Debug, Clone, Copy, Default)]
pub struct NativeFileHost;

#[derive(Debug, Error)]
pub enum NativeFileError {
    #[error("canonicalize authority root {path:?}: {source}")]
    CanonicalizeAuthorityRoot {
        path: PathBuf,
        #[source]
        source: io::Error,
    },
    #[error("authority root is not a directory: {0:?}")]
    AuthorityRootNotDirectory(PathBuf),
    #[error("canonicalize read path {path:?}: {source}")]
    CanonicalizeReadPath {
        path: PathBuf,
        #[source]
        source: io::Error,
    },
    #[error("write path has no parent: {0:?}")]
    MissingWriteParent(PathBuf),
    #[error("write path has no file name: {0:?}")]
    MissingWriteFileName(PathBuf),
    #[error("canonicalize write parent {path:?}: {source}")]
    CanonicalizeWriteParent {
        path: PathBuf,
        #[source]
        source: io::Error,
    },
    #[error("inspect write target {path:?}: {source}")]
    InspectWriteTarget {
        path: PathBuf,
        #[source]
        source: io::Error,
    },
    #[error("write target is a symbolic link: {0:?}")]
    SymbolicLinkWriteTarget(PathBuf),
    #[error("{operation} path {path:?} is outside authority root {root:?}")]
    OutsideAuthority {
        operation: &'static str,
        path: PathBuf,
        root: PathBuf,
    },
    #[error(transparent)]
    FileStore(#[from] FileStoreError),
}

fn canonical_root(root: &Path) -> Result<PathBuf, NativeFileError> {
    let canonical =
        fs::canonicalize(root).map_err(|source| NativeFileError::CanonicalizeAuthorityRoot {
            path: root.to_path_buf(),
            source,
        })?;
    if !canonical.is_dir() {
        return Err(NativeFileError::AuthorityRootNotDirectory(canonical));
    }
    Ok(canonical)
}

fn requested_path(root: &Path, path: &Path) -> PathBuf {
    if path.is_absolute() {
        path.to_path_buf()
    } else {
        root.join(path)
    }
}

fn ensure_contained(
    operation: &'static str,
    root: &Path,
    path: &Path,
) -> Result<(), NativeFileError> {
    if path.starts_with(root) {
        Ok(())
    } else {
        Err(NativeFileError::OutsideAuthority {
            operation,
            path: path.to_path_buf(),
            root: root.to_path_buf(),
        })
    }
}

fn authorize_read(authority: &FileReadAuthority, path: &Path) -> Result<PathBuf, NativeFileError> {
    let root = canonical_root(authority.root())?;
    let requested = requested_path(&root, path);
    let canonical =
        fs::canonicalize(&requested).map_err(|source| NativeFileError::CanonicalizeReadPath {
            path: requested,
            source,
        })?;
    ensure_contained("read", &root, &canonical)?;
    Ok(canonical)
}

fn authorize_write(
    authority: &FileWriteAuthority,
    path: &Path,
) -> Result<PathBuf, NativeFileError> {
    let root = canonical_root(authority.root())?;
    let requested = requested_path(&root, path);

    match fs::symlink_metadata(&requested) {
        Ok(metadata) if metadata.file_type().is_symlink() => {
            return Err(NativeFileError::SymbolicLinkWriteTarget(requested));
        }
        Ok(_) => {}
        Err(source) if source.kind() == io::ErrorKind::NotFound => {}
        Err(source) => {
            return Err(NativeFileError::InspectWriteTarget {
                path: requested,
                source,
            });
        }
    }

    let parent = requested
        .parent()
        .ok_or_else(|| NativeFileError::MissingWriteParent(requested.clone()))?;
    let canonical_parent =
        fs::canonicalize(parent).map_err(|source| NativeFileError::CanonicalizeWriteParent {
            path: parent.to_path_buf(),
            source,
        })?;
    ensure_contained("write", &root, &canonical_parent)?;

    let file_name = requested
        .file_name()
        .ok_or_else(|| NativeFileError::MissingWriteFileName(requested.clone()))?;
    Ok(canonical_parent.join(file_name))
}

impl FileHost for NativeFileHost {
    type Error = NativeFileError;

    fn read(&self, authority: &FileReadAuthority, path: &Path) -> Result<Vec<u8>, Self::Error> {
        let path = authorize_read(authority, path)?;
        read_file(path).map_err(NativeFileError::from)
    }

    fn write(
        &self,
        authority: &FileWriteAuthority,
        path: &Path,
        bytes: &[u8],
    ) -> Result<(), Self::Error> {
        let path = authorize_write(authority, path)?;
        write_atomic(path, bytes).map_err(NativeFileError::from)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Mutex;

    static TEST_LOCK: Mutex<()> = Mutex::new(());

    fn test_root(name: &str) -> PathBuf {
        std::env::temp_dir().join(format!(
            "audiagentic-host-native-{}-{name}",
            std::process::id()
        ))
    }

    #[test]
    fn round_trip_and_overwrite_are_authority_mediated() {
        let _test_guard = TEST_LOCK.lock().unwrap();
        let root = test_root("round-trip");
        let _ = fs::remove_dir_all(&root);
        fs::create_dir_all(&root).unwrap();

        let host = NativeFileHost;
        let read = FileReadAuthority::new(&root);
        let write = FileWriteAuthority::new(&root);
        let path = root.join("state.bin");

        host.write(&write, &path, b"one").unwrap();
        host.write(&write, &path, b"two").unwrap();
        assert_eq!(host.read(&read, &path).unwrap(), b"two");

        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn parent_escape_is_rejected_for_read_and_write() {
        let _test_guard = TEST_LOCK.lock().unwrap();
        let root = test_root("escape-root");
        let outside = test_root("escape-outside");
        let _ = fs::remove_dir_all(&root);
        let _ = fs::remove_dir_all(&outside);
        fs::create_dir_all(&root).unwrap();
        fs::create_dir_all(&outside).unwrap();
        fs::write(outside.join("state.bin"), b"outside").unwrap();

        let outside_name = outside.file_name().unwrap();
        let escaped = PathBuf::from("..").join(outside_name).join("state.bin");
        let host = NativeFileHost;
        let read = FileReadAuthority::new(&root);
        let write = FileWriteAuthority::new(&root);

        assert!(matches!(
            host.read(&read, &escaped).unwrap_err(),
            NativeFileError::OutsideAuthority { .. }
        ));
        assert!(matches!(
            host.write(&write, &escaped, b"blocked").unwrap_err(),
            NativeFileError::OutsideAuthority { .. }
        ));
        assert_eq!(fs::read(outside.join("state.bin")).unwrap(), b"outside");

        fs::remove_dir_all(root).unwrap();
        fs::remove_dir_all(outside).unwrap();
    }

    #[cfg(unix)]
    #[test]
    fn directory_symlink_escape_is_rejected() {
        use std::os::unix::fs::symlink;

        let _test_guard = TEST_LOCK.lock().unwrap();
        let root = test_root("symlink-root");
        let outside = test_root("symlink-outside");
        let _ = fs::remove_dir_all(&root);
        let _ = fs::remove_dir_all(&outside);
        fs::create_dir_all(&root).unwrap();
        fs::create_dir_all(&outside).unwrap();
        fs::write(outside.join("state.bin"), b"outside").unwrap();
        symlink(&outside, root.join("escape")).unwrap();

        let host = NativeFileHost;
        let read = FileReadAuthority::new(&root);
        let write = FileWriteAuthority::new(&root);
        let escaped = root.join("escape").join("state.bin");

        assert!(matches!(
            host.read(&read, &escaped).unwrap_err(),
            NativeFileError::OutsideAuthority { .. }
        ));
        assert!(matches!(
            host.write(&write, &escaped, b"blocked").unwrap_err(),
            NativeFileError::OutsideAuthority { .. }
        ));
        assert_eq!(fs::read(outside.join("state.bin")).unwrap(), b"outside");

        fs::remove_dir_all(root).unwrap();
        fs::remove_dir_all(outside).unwrap();
    }

    #[cfg(unix)]
    #[test]
    fn write_to_symlink_leaf_is_rejected() {
        use std::os::unix::fs::symlink;

        let _test_guard = TEST_LOCK.lock().unwrap();
        let root = test_root("leaf-symlink-root");
        let outside = test_root("leaf-symlink-outside");
        let _ = fs::remove_dir_all(&root);
        let _ = fs::remove_dir_all(&outside);
        fs::create_dir_all(&root).unwrap();
        fs::create_dir_all(&outside).unwrap();
        let outside_file = outside.join("state.bin");
        fs::write(&outside_file, b"outside").unwrap();
        let link = root.join("state.bin");
        symlink(&outside_file, &link).unwrap();

        let host = NativeFileHost;
        let write = FileWriteAuthority::new(&root);
        assert!(matches!(
            host.write(&write, &link, b"blocked").unwrap_err(),
            NativeFileError::SymbolicLinkWriteTarget(_)
        ));
        assert_eq!(fs::read(outside_file).unwrap(), b"outside");

        fs::remove_dir_all(root).unwrap();
        fs::remove_dir_all(outside).unwrap();
    }
}
