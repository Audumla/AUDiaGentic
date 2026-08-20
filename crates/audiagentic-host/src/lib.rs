//! Narrow host-facility contracts with explicit authority scopes.
//!
//! This crate provides boundaries, not a global host container. Applications
//! pass only the facility and authority a capability actually needs.

use std::{
    collections::BTreeSet,
    error::Error,
    ffi::OsString,
    future::Future,
    path::{Path, PathBuf},
    pin::Pin,
};

use audiagentic_core::ExecutionContext;
use audiagentic_sensitive::{SafeMetadata, Secret};

pub type HostFuture<'a, T> = Pin<Box<dyn Future<Output = T> + Send + 'a>>;

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

    pub fn allows(&self, program: &Path) -> bool {
        self.programs.contains(program)
    }
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct NetworkAuthority {
    hosts: BTreeSet<String>,
}

impl NetworkAuthority {
    pub fn new(hosts: impl IntoIterator<Item = String>) -> Self {
        Self {
            hosts: hosts.into_iter().collect(),
        }
    }

    pub fn allows(&self, host: &str) -> bool {
        self.hosts.contains(host)
    }
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct SecretAuthority {
    names: BTreeSet<String>,
}

impl SecretAuthority {
    pub fn new(names: impl IntoIterator<Item = String>) -> Self {
        Self {
            names: names.into_iter().collect(),
        }
    }

    pub fn allows(&self, name: &str) -> bool {
        self.names.contains(name)
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ProcessRequest {
    pub program: PathBuf,
    pub args: Vec<OsString>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ProcessOutput {
    pub exit_code: Option<i32>,
    pub stdout: Vec<u8>,
    pub stderr: Vec<u8>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NetworkRequest {
    pub method: String,
    pub url: String,
    pub body: Vec<u8>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NetworkResponse {
    pub status: u16,
    pub body: Vec<u8>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EventRecord {
    pub name: String,
    pub execution: ExecutionContext,
    pub metadata: SafeMetadata,
}

pub trait FileHost: Send + Sync {
    type Error: Error + Send + Sync + 'static;

    fn read<'a>(
        &'a self,
        authority: &'a FileReadAuthority,
        path: &'a Path,
    ) -> HostFuture<'a, Result<Vec<u8>, Self::Error>>;

    fn write<'a>(
        &'a self,
        authority: &'a FileWriteAuthority,
        path: &'a Path,
        bytes: &'a [u8],
    ) -> HostFuture<'a, Result<(), Self::Error>>;
}

pub trait ProcessHost: Send + Sync {
    type Error: Error + Send + Sync + 'static;

    fn run<'a>(
        &'a self,
        authority: &'a ProcessAuthority,
        request: ProcessRequest,
    ) -> HostFuture<'a, Result<ProcessOutput, Self::Error>>;
}

pub trait NetworkHost: Send + Sync {
    type Error: Error + Send + Sync + 'static;

    fn send<'a>(
        &'a self,
        authority: &'a NetworkAuthority,
        request: NetworkRequest,
    ) -> HostFuture<'a, Result<NetworkResponse, Self::Error>>;
}

pub trait SecretHost: Send + Sync {
    type Error: Error + Send + Sync + 'static;

    fn read_secret<'a>(
        &'a self,
        authority: &'a SecretAuthority,
        name: &'a str,
    ) -> HostFuture<'a, Result<Secret<Vec<u8>>, Self::Error>>;
}

pub trait EventSink: Send + Sync {
    type Error: Error + Send + Sync + 'static;

    fn emit<'a>(&'a self, event: EventRecord) -> HostFuture<'a, Result<(), Self::Error>>;
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn authorities_are_narrow_and_explicit() {
        let files = FileWriteAuthority::new("/tmp/app");
        assert_eq!(files.root(), Path::new("/tmp/app"));

        let processes = ProcessAuthority::new([PathBuf::from("/usr/bin/git")]);
        assert!(processes.allows(Path::new("/usr/bin/git")));
        assert!(!processes.allows(Path::new("/bin/sh")));

        let network = NetworkAuthority::new(["example.com".to_owned()]);
        assert!(network.allows("example.com"));
        assert!(!network.allows("other.example"));
    }
}
