//! Narrow host-facility contracts with explicit authority scopes.
//!
//! This crate provides boundaries, not a global host container. Applications
//! pass only the facility and authority a capability actually needs. New host
//! contracts are added only when a real capability proves their semantics.

use std::{
    collections::BTreeSet,
    error::Error,
    ffi::{OsStr, OsString},
    fmt,
    io::{Read, Write},
    path::{Path, PathBuf},
};

use audiagentic_sensitive::Secret;

/// A filesystem read grant. The grant carries the configured root only;
/// concrete host implementations must canonicalize and enforce containment.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FileReadAuthority {
    root: PathBuf,
}

impl FileReadAuthority {
    pub fn new(root: impl Into<PathBuf>) -> Self {
        Self { root: root.into() }
    }

    pub fn root(&self) -> &Path {
        &self.root
    }
}

/// A filesystem write grant. The grant deliberately has no lexical `allows`
/// helper because path prefix checks are not a safe substitute for platform
/// canonicalization and symlink-aware enforcement.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FileWriteAuthority {
    root: PathBuf,
}

impl FileWriteAuthority {
    pub fn new(root: impl Into<PathBuf>) -> Self {
        Self { root: root.into() }
    }

    pub fn root(&self) -> &Path {
        &self.root
    }
}

/// Permission to launch a bounded set of executable paths.
///
/// This is launch authority, not a child-process sandbox: once started, a
/// native process has the operating-system authority of its account unless a
/// stronger platform sandbox is applied by a later concrete host.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct ProcessAuthority {
    programs: BTreeSet<PathBuf>,
}

impl ProcessAuthority {
    pub fn new(programs: impl IntoIterator<Item = PathBuf>) -> Self {
        Self {
            programs: programs.into_iter().collect(),
        }
    }

    pub fn programs(&self) -> &BTreeSet<PathBuf> {
        &self.programs
    }
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub enum ProcessStdio {
    #[default]
    Pipe,
    Null,
    Inherit,
}

/// Description of a managed child process. Environment values are represented
/// as `Secret` so debug output cannot expose them accidentally.
pub struct ProcessRequest {
    program: PathBuf,
    args: Vec<OsString>,
    current_dir: Option<PathBuf>,
    environment: Vec<(OsString, Secret<OsString>)>,
    inherit_environment: bool,
    stdin: ProcessStdio,
    stdout: ProcessStdio,
    stderr: ProcessStdio,
}

impl ProcessRequest {
    pub fn new(program: impl Into<PathBuf>) -> Self {
        Self {
            program: program.into(),
            args: Vec::new(),
            current_dir: None,
            environment: Vec::new(),
            inherit_environment: false,
            stdin: ProcessStdio::Pipe,
            stdout: ProcessStdio::Pipe,
            stderr: ProcessStdio::Pipe,
        }
    }

    pub fn program(&self) -> &Path {
        &self.program
    }

    pub fn args(&self) -> &[OsString] {
        &self.args
    }

    pub fn current_dir(&self) -> Option<&Path> {
        self.current_dir.as_deref()
    }

    pub fn environment(&self) -> impl Iterator<Item = (&OsStr, &Secret<OsString>)> {
        self.environment
            .iter()
            .map(|(key, value)| (key.as_os_str(), value))
    }

    pub fn inherits_environment(&self) -> bool {
        self.inherit_environment
    }

    pub fn stdin_mode(&self) -> ProcessStdio {
        self.stdin
    }

    pub fn stdout_mode(&self) -> ProcessStdio {
        self.stdout
    }

    pub fn stderr_mode(&self) -> ProcessStdio {
        self.stderr
    }

    pub fn arg(mut self, arg: impl Into<OsString>) -> Self {
        self.args.push(arg.into());
        self
    }

    pub fn args_from(mut self, args: impl IntoIterator<Item = OsString>) -> Self {
        self.args.extend(args);
        self
    }

    pub fn current_dir_path(mut self, path: impl Into<PathBuf>) -> Self {
        self.current_dir = Some(path.into());
        self
    }

    pub fn env_secret(mut self, key: impl Into<OsString>, value: Secret<OsString>) -> Self {
        self.environment.push((key.into(), value));
        self
    }

    pub fn inherit_environment(mut self, inherit: bool) -> Self {
        self.inherit_environment = inherit;
        self
    }

    pub fn stdin(mut self, mode: ProcessStdio) -> Self {
        self.stdin = mode;
        self
    }

    pub fn stdout(mut self, mode: ProcessStdio) -> Self {
        self.stdout = mode;
        self
    }

    pub fn stderr(mut self, mode: ProcessStdio) -> Self {
        self.stderr = mode;
        self
    }
}

impl fmt::Debug for ProcessRequest {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("ProcessRequest")
            .field("program", &self.program)
            .field("args", &self.args)
            .field("current_dir", &self.current_dir)
            .field(
                "environment_keys",
                &self
                    .environment
                    .iter()
                    .map(|(key, _)| key)
                    .collect::<Vec<_>>(),
            )
            .field("inherit_environment", &self.inherit_environment)
            .field("stdin", &self.stdin)
            .field("stdout", &self.stdout)
            .field("stderr", &self.stderr)
            .finish()
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ProcessExit {
    code: Option<i32>,
    success: bool,
}

impl ProcessExit {
    pub fn new(code: Option<i32>, success: bool) -> Self {
        Self { code, success }
    }

    pub fn code(self) -> Option<i32> {
        self.code
    }

    pub fn success(self) -> bool {
        self.success
    }
}

/// Filesystem access is synchronous at this contract boundary. Native
/// filesystem operations are blocking and WIT filesystem calls are naturally
/// synchronous; runtimes that require offloading may adapt this contract at
/// their runtime edge rather than forcing an async framework into foundation.
pub trait FileHost: Send + Sync {
    type Error: Error + Send + Sync + 'static;

    fn read(&self, authority: &FileReadAuthority, path: &Path) -> Result<Vec<u8>, Self::Error>;

    fn read_optional(
        &self,
        authority: &FileReadAuthority,
        path: &Path,
    ) -> Result<Option<Vec<u8>>, Self::Error>;

    fn write(
        &self,
        authority: &FileWriteAuthority,
        path: &Path,
        bytes: &[u8],
    ) -> Result<(), Self::Error>;

    fn remove(&self, authority: &FileWriteAuthority, path: &Path) -> Result<(), Self::Error>;
}

/// Owned child-process lifecycle. Blocking stdio is exposed deliberately at
/// this low-level boundary; an application/runtime may adapt it onto threads or
/// an async reactor without making Tokio part of the host contract.
pub trait ProcessChild: Send {
    type Error: Error + Send + Sync + 'static;

    fn id(&self) -> u32;
    fn stdin(&mut self) -> Option<&mut (dyn Write + Send)>;
    fn stdout(&mut self) -> Option<&mut (dyn Read + Send)>;
    fn stderr(&mut self) -> Option<&mut (dyn Read + Send)>;
    fn take_stdin(&mut self) -> Option<Box<dyn Write + Send>>;
    fn take_stdout(&mut self) -> Option<Box<dyn Read + Send>>;
    fn take_stderr(&mut self) -> Option<Box<dyn Read + Send>>;
    fn try_wait(&mut self) -> Result<Option<ProcessExit>, Self::Error>;
    fn wait(&mut self) -> Result<ProcessExit, Self::Error>;
    fn kill(&mut self) -> Result<(), Self::Error>;

    fn close_stdin(&mut self) {
        drop(self.take_stdin());
    }

    fn is_running(&mut self) -> Result<bool, Self::Error> {
        Ok(self.try_wait()?.is_none())
    }
}

/// Process creation returns an owned child rather than collapsing a harness
/// session into a one-shot `run()` call.
pub trait ProcessHost: Send + Sync {
    type Error: Error + Send + Sync + 'static;
    type Child: ProcessChild<Error = Self::Error>;

    fn spawn(
        &self,
        authority: &ProcessAuthority,
        request: ProcessRequest,
    ) -> Result<Self::Child, Self::Error>;
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn authorities_are_narrow_and_explicit() {
        let files = FileWriteAuthority::new("/tmp/app");
        assert_eq!(files.root(), Path::new("/tmp/app"));

        let processes = ProcessAuthority::new([PathBuf::from("/usr/bin/git")]);
        assert!(processes.programs().contains(Path::new("/usr/bin/git")));
        assert!(!processes.programs().contains(Path::new("/bin/sh")));
    }

    #[test]
    fn process_request_redacts_environment_values_and_exposes_stdio_policy() {
        let request = ProcessRequest::new("/bin/tool")
            .env_secret("TOKEN", Secret::new(OsString::from("never-log-me")))
            .stderr(ProcessStdio::Null);
        let debug = format!("{request:?}");
        assert!(debug.contains("TOKEN"));
        assert!(!debug.contains("never-log-me"));
        assert_eq!(request.stderr_mode(), ProcessStdio::Null);
    }
}
