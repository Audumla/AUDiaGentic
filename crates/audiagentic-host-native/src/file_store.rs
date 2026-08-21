use std::{
    fs::{self, File, OpenOptions},
    io::{self, Write},
    path::{Path, PathBuf},
    sync::atomic::{AtomicU64, Ordering},
};

static TEMP_COUNTER: AtomicU64 = AtomicU64::new(1);
const TEMP_CREATE_ATTEMPTS: usize = 16;

/// Private durability operations surface as ordinary I/O failures to the
/// enclosing native host. The file-store module remains an implementation
/// detail rather than creating a second public error/API boundary.
pub type FileStoreError = io::Error;

fn io_error(operation: &'static str, path: &Path, source: io::Error) -> FileStoreError {
    io::Error::new(
        source.kind(),
        format!("{operation} {path:?}: {source}"),
    )
}

fn temporary_path(path: &Path, id: u64) -> Result<PathBuf, FileStoreError> {
    let name = path
        .file_name()
        .ok_or_else(|| {
            io::Error::new(
                io::ErrorKind::InvalidInput,
                format!("path has no file name: {path:?}"),
            )
        })?
        .to_string_lossy();
    Ok(path.with_file_name(format!(".{name}.tmp-{}-{id}", std::process::id())))
}

fn next_temporary_path(path: &Path) -> Result<PathBuf, FileStoreError> {
    let id = TEMP_COUNTER.fetch_add(1, Ordering::Relaxed);
    temporary_path(path, id)
}

fn create_temporary_file(path: &Path) -> Result<(PathBuf, File), FileStoreError> {
    for _ in 0..TEMP_CREATE_ATTEMPTS {
        let temp = next_temporary_path(path)?;
        match OpenOptions::new().write(true).create_new(true).open(&temp) {
            Ok(file) => return Ok((temp, file)),
            Err(source) if source.kind() == io::ErrorKind::AlreadyExists => continue,
            Err(source) => return Err(io_error("create temporary file", &temp, source)),
        }
    }

    Err(io_error(
        "create temporary file",
        path,
        io::Error::new(
            io::ErrorKind::AlreadyExists,
            "exhausted temporary file name attempts",
        ),
    ))
}

struct TempGuard(Option<PathBuf>);

impl TempGuard {
    fn new(path: PathBuf) -> Self {
        Self(Some(path))
    }

    fn disarm(&mut self) {
        self.0 = None;
    }
}

impl Drop for TempGuard {
    fn drop(&mut self) {
        if let Some(path) = self.0.as_ref() {
            let _ = fs::remove_file(path);
        }
    }
}

pub(super) fn read(path: impl AsRef<Path>) -> Result<Vec<u8>, FileStoreError> {
    let path = path.as_ref();
    fs::read(path).map_err(|source| io_error("read", path, source))
}

/// Write through a same-directory temporary file, fsync it, atomically rename
/// it over the destination, then fsync the parent on Unix. This is a private
/// implementation detail of `NativeFileHost`, not an application storage API.
pub(super) fn write_atomic(path: impl AsRef<Path>, bytes: &[u8]) -> Result<(), FileStoreError> {
    let path = path.as_ref();
    let parent = path
        .parent()
        .filter(|p| !p.as_os_str().is_empty())
        .unwrap_or(Path::new("."));
    fs::create_dir_all(parent).map_err(|source| io_error("create parent", parent, source))?;

    let (temp, mut file) = create_temporary_file(path)?;
    let mut guard = TempGuard::new(temp.clone());
    file.write_all(bytes)
        .map_err(|source| io_error("write temporary file", &temp, source))?;
    file.sync_all()
        .map_err(|source| io_error("fsync temporary file", &temp, source))?;
    drop(file);

    fs::rename(&temp, path).map_err(|source| io_error("replace destination", path, source))?;
    guard.disarm();

    #[cfg(unix)]
    {
        let directory =
            File::open(parent).map_err(|source| io_error("open parent", parent, source))?;
        directory
            .sync_all()
            .map_err(|source| io_error("fsync parent", parent, source))?;
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Mutex;

    static TEST_LOCK: Mutex<()> = Mutex::new(());

    fn test_path(name: &str) -> PathBuf {
        std::env::temp_dir().join(format!(
            "audiagentic-native-file-store-{}-{name}",
            std::process::id()
        ))
    }

    #[test]
    fn writes_and_reads_new_file() {
        let _test_guard = TEST_LOCK.lock().unwrap();
        let directory = test_path("new");
        let path = directory.join("state.bin");
        let _ = fs::remove_dir_all(&directory);
        write_atomic(&path, b"state").unwrap();
        assert_eq!(read(&path).unwrap(), b"state");
        fs::remove_dir_all(directory).unwrap();
    }

    #[test]
    fn temporary_name_collision_is_preserved_and_retried() {
        let _test_guard = TEST_LOCK.lock().unwrap();
        let directory = test_path("collision");
        let path = directory.join("state.bin");
        let _ = fs::remove_dir_all(&directory);
        fs::create_dir_all(&directory).unwrap();

        let next_id = TEMP_COUNTER.load(Ordering::Relaxed);
        let collision = temporary_path(&path, next_id).unwrap();
        fs::write(&collision, b"owned elsewhere").unwrap();

        write_atomic(&path, b"state").unwrap();

        assert_eq!(read(&collision).unwrap(), b"owned elsewhere");
        assert_eq!(read(&path).unwrap(), b"state");
        fs::remove_dir_all(directory).unwrap();
    }

    #[test]
    fn replaces_existing_file_atomically() {
        let _test_guard = TEST_LOCK.lock().unwrap();
        let directory = test_path("replace");
        let path = directory.join("state.bin");
        let _ = fs::remove_dir_all(&directory);
        write_atomic(&path, b"one").unwrap();
        write_atomic(&path, b"two").unwrap();
        assert_eq!(read(&path).unwrap(), b"two");
        fs::remove_dir_all(directory).unwrap();
    }
}
