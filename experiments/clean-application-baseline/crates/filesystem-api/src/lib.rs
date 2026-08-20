use std::path::{Component, Path, PathBuf};

use async_trait::async_trait;
use thiserror::Error;

#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct RelativePath(PathBuf);

impl RelativePath {
    pub fn new(path: impl AsRef<Path>) -> Result<Self, FileSystemError> {
        let path = path.as_ref();
        if path.as_os_str().is_empty()
            || path
                .components()
                .any(|part| !matches!(part, Component::Normal(_)))
        {
            return Err(FileSystemError::InvalidPath(path.display().to_string()));
        }
        Ok(Self(path.to_owned()))
    }

    pub fn as_path(&self) -> &Path {
        &self.0
    }
}

#[derive(Clone, Debug, Error, PartialEq, Eq)]
pub enum FileSystemError {
    #[error("invalid relative path `{0}`")]
    InvalidPath(String),
    #[error("file not found: `{0}`")]
    NotFound(String),
    #[error("filesystem access denied: `{0}`")]
    Denied(String),
    #[error("filesystem I/O failed: `{0}`")]
    Io(String),
}

#[async_trait]
pub trait FileSystem: Send + Sync {
    async fn read_text(&self, path: &RelativePath) -> Result<Option<String>, FileSystemError>;
    async fn write_text_atomic(
        &self,
        path: &RelativePath,
        content: String,
    ) -> Result<(), FileSystemError>;
    async fn remove_file(&self, path: &RelativePath) -> Result<bool, FileSystemError>;
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn relative_paths_reject_ambient_or_parent_authority() {
        assert!(RelativePath::new("../secret").is_err());
        assert!(RelativePath::new("/etc/passwd").is_err());
        assert!(RelativePath::new("config/app.json").is_ok());
    }
}
