//! Native host-facility implementations.
//!
//! This crate implements concrete operating-system behavior behind the narrow
//! contracts in `audiagentic-host`. It does not aggregate facilities into a
//! global host object.

use std::{
    fs,
    io::{self, Read, Write},
    path::{Path, PathBuf},
    process::{Child, ChildStderr, ChildStdin, ChildStdout, Command, ExitStatus, Stdio},
};

use audiagentic_file_store::{FileStoreError, read as read_file, write_atomic};
use audiagentic_host::{
    FileHost, FileReadAuthority, FileWriteAuthority, ProcessAuthority, ProcessChild, ProcessExit,
    ProcessHost, ProcessRequest, ProcessStdio,
};
use thiserror::Error;

#[derive(Debug, Clone, Copy, Default)]
pub struct NativeFileHost;

#[derive(Debug, Clone, Copy, Default)]
pub struct NativeProcessHost;

#[derive(Debug, Error)]
pub enum NativeHostError {
    #[error("canonicalize authority root {path:?}: {source}")]
    CanonicalizeAuthorityRoot {
        path: PathBuf,
        #[source]
        source: io::Error,
    },
    #[error("authority root is not a directory: {0:?}")]
    AuthorityRootNotDirectory(PathBuf),
    #[error("inspect read target {path:?}: {source}")]
    InspectReadTarget {
        path: PathBuf,
        #[source]
        source: io::Error,
    },
    #[error("canonicalize read path {path:?}: {source}")]
    CanonicalizeReadPath {
        path: PathBuf,
        #[source]
        source: io::Error,
    },
    #[error("read path has no parent: {0:?}")]
    MissingReadParent(PathBuf),
    #[error("canonicalize read parent {path:?}: {source}")]
    CanonicalizeReadParent {
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
    #[error("remove file {path:?}: {source}")]
    RemoveFile {
        path: PathBuf,
        #[source]
        source: io::Error,
    },
    #[error("{operation} path {path:?} is outside authority root {root:?}")]
    OutsideAuthority {
        operation: &'static str,
        path: PathBuf,
        root: PathBuf,
    },
    #[error("canonicalize process program {path:?}: {source}")]
    CanonicalizeProcessProgram {
        path: PathBuf,
        #[source]
        source: io::Error,
    },
    #[error("process program is not authorized: {0:?}")]
    ProcessProgramNotAuthorized(PathBuf),
    #[error("spawn process {program:?}: {source}")]
    SpawnProcess {
        program: PathBuf,
        #[source]
        source: io::Error,
    },
    #[error("inspect process {pid}: {source}")]
    InspectProcess {
        pid: u32,
        #[source]
        source: io::Error,
    },
    #[error("wait for process {pid}: {source}")]
    WaitProcess {
        pid: u32,
        #[source]
        source: io::Error,
    },
    #[error("kill process {pid}: {source}")]
    KillProcess {
        pid: u32,
        #[source]
        source: io::Error,
    },
    #[error(transparent)]
    FileStore(#[from] FileStoreError),
}

pub type NativeFileError = NativeHostError;
pub type NativeProcessError = NativeHostError;

fn canonical_root(root: &Path) -> Result<PathBuf, NativeHostError> {
    let canonical =
        fs::canonicalize(root).map_err(|source| NativeHostError::CanonicalizeAuthorityRoot {
            path: root.to_path_buf(),
            source,
        })?;
    if !canonical.is_dir() {
        return Err(NativeHostError::AuthorityRootNotDirectory(canonical));
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
) -> Result<(), NativeHostError> {
    if path.starts_with(root) {
        Ok(())
    } else {
        Err(NativeHostError::OutsideAuthority {
            operation,
            path: path.to_path_buf(),
            root: root.to_path_buf(),
        })
    }
}

fn authorize_read(authority: &FileReadAuthority, path: &Path) -> Result<PathBuf, NativeHostError> {
    let root = canonical_root(authority.root())?;
    let requested = requested_path(&root, path);
    let canonical =
        fs::canonicalize(&requested).map_err(|source| NativeHostError::CanonicalizeReadPath {
            path: requested,
            source,
        })?;
    ensure_contained("read", &root, &canonical)?;
    Ok(canonical)
}

fn authorize_optional_read(
    authority: &FileReadAuthority,
    path: &Path,
) -> Result<Option<PathBuf>, NativeHostError> {
    let root = canonical_root(authority.root())?;
    let requested = requested_path(&root, path);

    match fs::symlink_metadata(&requested) {
        Ok(_) => {
            let canonical = fs::canonicalize(&requested).map_err(|source| {
                NativeHostError::CanonicalizeReadPath {
                    path: requested,
                    source,
                }
            })?;
            ensure_contained("read", &root, &canonical)?;
            Ok(Some(canonical))
        }
        Err(source) if source.kind() == io::ErrorKind::NotFound => {
            let parent = requested
                .parent()
                .ok_or_else(|| NativeHostError::MissingReadParent(requested.clone()))?;
            let canonical_parent = fs::canonicalize(parent).map_err(|source| {
                NativeHostError::CanonicalizeReadParent {
                    path: parent.to_path_buf(),
                    source,
                }
            })?;
            ensure_contained("read", &root, &canonical_parent)?;
            Ok(None)
        }
        Err(source) => Err(NativeHostError::InspectReadTarget {
            path: requested,
            source,
        }),
    }
}

fn authorize_write(
    authority: &FileWriteAuthority,
    path: &Path,
) -> Result<PathBuf, NativeHostError> {
    let root = canonical_root(authority.root())?;
    let requested = requested_path(&root, path);

    match fs::symlink_metadata(&requested) {
        Ok(metadata) if metadata.file_type().is_symlink() => {
            return Err(NativeHostError::SymbolicLinkWriteTarget(requested));
        }
        Ok(_) => {}
        Err(source) if source.kind() == io::ErrorKind::NotFound => {}
        Err(source) => {
            return Err(NativeHostError::InspectWriteTarget {
                path: requested,
                source,
            });
        }
    }

    let parent = requested
        .parent()
        .ok_or_else(|| NativeHostError::MissingWriteParent(requested.clone()))?;
    let canonical_parent =
        fs::canonicalize(parent).map_err(|source| NativeHostError::CanonicalizeWriteParent {
            path: parent.to_path_buf(),
            source,
        })?;
    ensure_contained("write", &root, &canonical_parent)?;

    let file_name = requested
        .file_name()
        .ok_or_else(|| NativeHostError::MissingWriteFileName(requested.clone()))?;
    Ok(canonical_parent.join(file_name))
}

fn canonical_program(path: &Path) -> Result<PathBuf, NativeHostError> {
    fs::canonicalize(path).map_err(|source| NativeHostError::CanonicalizeProcessProgram {
        path: path.to_path_buf(),
        source,
    })
}

fn authorize_program(
    authority: &ProcessAuthority,
    requested: &Path,
) -> Result<PathBuf, NativeHostError> {
    let requested = canonical_program(requested)?;
    for allowed in authority.programs() {
        if canonical_program(allowed)? == requested {
            return Ok(requested);
        }
    }
    Err(NativeHostError::ProcessProgramNotAuthorized(requested))
}

fn process_exit(status: ExitStatus) -> ProcessExit {
    ProcessExit::new(status.code(), status.success())
}

fn process_stdio(mode: ProcessStdio) -> Stdio {
    match mode {
        ProcessStdio::Pipe => Stdio::piped(),
        ProcessStdio::Null => Stdio::null(),
        ProcessStdio::Inherit => Stdio::inherit(),
    }
}

impl FileHost for NativeFileHost {
    type Error = NativeHostError;

    fn read(&self, authority: &FileReadAuthority, path: &Path) -> Result<Vec<u8>, Self::Error> {
        let path = authorize_read(authority, path)?;
        read_file(path).map_err(NativeHostError::from)
    }

    fn read_optional(
        &self,
        authority: &FileReadAuthority,
        path: &Path,
    ) -> Result<Option<Vec<u8>>, Self::Error> {
        let Some(path) = authorize_optional_read(authority, path)? else {
            return Ok(None);
        };
        read_file(path).map(Some).map_err(NativeHostError::from)
    }

    fn write(
        &self,
        authority: &FileWriteAuthority,
        path: &Path,
        bytes: &[u8],
    ) -> Result<(), Self::Error> {
        let path = authorize_write(authority, path)?;
        write_atomic(path, bytes).map_err(NativeHostError::from)
    }

    fn remove(&self, authority: &FileWriteAuthority, path: &Path) -> Result<(), Self::Error> {
        let path = authorize_write(authority, path)?;
        fs::remove_file(&path).map_err(|source| NativeHostError::RemoveFile { path, source })
    }
}

pub struct NativeProcess {
    child: Child,
    stdin: Option<ChildStdin>,
    stdout: Option<ChildStdout>,
    stderr: Option<ChildStderr>,
}

impl NativeProcess {
    fn from_child(mut child: Child) -> Self {
        let stdin = child.stdin.take();
        let stdout = child.stdout.take();
        let stderr = child.stderr.take();
        Self {
            child,
            stdin,
            stdout,
            stderr,
        }
    }
}

impl ProcessChild for NativeProcess {
    type Error = NativeHostError;

    fn id(&self) -> u32 {
        self.child.id()
    }

    fn stdin(&mut self) -> Option<&mut (dyn Write + Send)> {
        self.stdin
            .as_mut()
            .map(|stdin| stdin as &mut (dyn Write + Send))
    }

    fn stdout(&mut self) -> Option<&mut (dyn Read + Send)> {
        self.stdout
            .as_mut()
            .map(|stdout| stdout as &mut (dyn Read + Send))
    }

    fn stderr(&mut self) -> Option<&mut (dyn Read + Send)> {
        self.stderr
            .as_mut()
            .map(|stderr| stderr as &mut (dyn Read + Send))
    }

    fn take_stdin(&mut self) -> Option<Box<dyn Write + Send>> {
        self.stdin
            .take()
            .map(|stdin| Box::new(stdin) as Box<dyn Write + Send>)
    }

    fn take_stdout(&mut self) -> Option<Box<dyn Read + Send>> {
        self.stdout
            .take()
            .map(|stdout| Box::new(stdout) as Box<dyn Read + Send>)
    }

    fn take_stderr(&mut self) -> Option<Box<dyn Read + Send>> {
        self.stderr
            .take()
            .map(|stderr| Box::new(stderr) as Box<dyn Read + Send>)
    }

    fn try_wait(&mut self) -> Result<Option<ProcessExit>, Self::Error> {
        let pid = self.id();
        self.child
            .try_wait()
            .map(|status| status.map(process_exit))
            .map_err(|source| NativeHostError::InspectProcess { pid, source })
    }

    fn wait(&mut self) -> Result<ProcessExit, Self::Error> {
        let pid = self.id();
        self.child
            .wait()
            .map(process_exit)
            .map_err(|source| NativeHostError::WaitProcess { pid, source })
    }

    fn kill(&mut self) -> Result<(), Self::Error> {
        let pid = self.id();
        if self.try_wait()?.is_some() {
            return Ok(());
        }
        self.child
            .kill()
            .map_err(|source| NativeHostError::KillProcess { pid, source })
    }
}

impl Drop for NativeProcess {
    fn drop(&mut self) {
        if matches!(self.child.try_wait(), Ok(None)) {
            let _ = self.child.kill();
            let _ = self.child.wait();
        }
    }
}

impl ProcessHost for NativeProcessHost {
    type Error = NativeHostError;
    type Child = NativeProcess;

    fn spawn(
        &self,
        authority: &ProcessAuthority,
        request: ProcessRequest,
    ) -> Result<Self::Child, Self::Error> {
        let program = authorize_program(authority, request.program())?;
        let mut command = Command::new(&program);
        command.args(request.args());
        command.stdin(process_stdio(request.stdin_mode()));
        command.stdout(process_stdio(request.stdout_mode()));
        command.stderr(process_stdio(request.stderr_mode()));

        if let Some(current_dir) = request.current_dir() {
            command.current_dir(current_dir);
        }
        if !request.inherits_environment() {
            command.env_clear();
        }
        for (key, value) in request.environment() {
            command.env(key, value.expose());
        }

        let child = command
            .spawn()
            .map_err(|source| NativeHostError::SpawnProcess {
                program: program.clone(),
                source,
            })?;
        Ok(NativeProcess::from_child(child))
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
    fn round_trip_overwrite_optional_read_and_remove_are_authority_mediated() {
        let _test_guard = TEST_LOCK.lock().unwrap();
        let root = test_root("round-trip");
        let _ = fs::remove_dir_all(&root);
        fs::create_dir_all(&root).unwrap();

        let host = NativeFileHost;
        let read = FileReadAuthority::new(&root);
        let write = FileWriteAuthority::new(&root);
        let path = root.join("state.bin");

        assert_eq!(host.read_optional(&read, &path).unwrap(), None);
        host.write(&write, &path, b"one").unwrap();
        host.write(&write, &path, b"two").unwrap();
        assert_eq!(host.read(&read, &path).unwrap(), b"two");
        assert_eq!(
            host.read_optional(&read, &path).unwrap(),
            Some(b"two".to_vec())
        );
        host.remove(&write, &path).unwrap();
        assert_eq!(host.read_optional(&read, &path).unwrap(), None);

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
            NativeHostError::OutsideAuthority { .. }
        ));
        assert!(matches!(
            host.write(&write, &escaped, b"blocked").unwrap_err(),
            NativeHostError::OutsideAuthority { .. }
        ));
        assert_eq!(fs::read(outside.join("state.bin")).unwrap(), b"outside");

        fs::remove_dir_all(root).unwrap();
        fs::remove_dir_all(outside).unwrap();
    }

    #[test]
    fn process_program_outside_allowlist_is_rejected() {
        let current = std::env::current_exe().unwrap();
        let authority = ProcessAuthority::new(std::iter::empty());
        let result = NativeProcessHost.spawn(&authority, ProcessRequest::new(current));
        assert!(matches!(
            result,
            Err(NativeHostError::ProcessProgramNotAuthorized(_))
        ));
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
            NativeHostError::OutsideAuthority { .. }
        ));
        assert!(matches!(
            host.write(&write, &escaped, b"blocked").unwrap_err(),
            NativeHostError::OutsideAuthority { .. }
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
            NativeHostError::SymbolicLinkWriteTarget(_)
        ));
        assert_eq!(fs::read(outside_file).unwrap(), b"outside");

        fs::remove_dir_all(root).unwrap();
        fs::remove_dir_all(outside).unwrap();
    }
}
