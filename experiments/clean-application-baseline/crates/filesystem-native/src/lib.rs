use std::{
    io::{self, Write},
    path::{Path, PathBuf},
    sync::Arc,
};

use async_trait::async_trait;
use audiagentic_filesystem_api_spike::{FileSystem, FileSystemError, RelativePath};
use cap_std::{ambient_authority, fs::Dir};

#[derive(Clone)]
pub struct NativeFileSystem {
    root: Arc<Dir>,
}

impl NativeFileSystem {
    pub fn open(root: impl AsRef<Path>) -> Result<Self, FileSystemError> {
        let root_path = root.as_ref();
        let root = Dir::open_ambient_dir(root_path, ambient_authority())
            .map_err(|error| map_io(root_path, error))?;
        Ok(Self {
            root: Arc::new(root),
        })
    }
}

#[async_trait]
impl FileSystem for NativeFileSystem {
    async fn read_text(&self, path: &RelativePath) -> Result<Option<String>, FileSystemError> {
        let root = self.root.clone();
        let path = path.as_path().to_owned();
        tokio::task::spawn_blocking(move || match root.read_to_string(&path) {
            Ok(value) => Ok(Some(value)),
            Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(None),
            Err(error) => Err(map_io(&path, error)),
        })
        .await
        .map_err(|error| FileSystemError::Io(error.to_string()))?
    }

    async fn write_text_atomic(
        &self,
        path: &RelativePath,
        content: String,
    ) -> Result<(), FileSystemError> {
        let root = self.root.clone();
        let path = path.as_path().to_owned();
        tokio::task::spawn_blocking(move || atomic_write(&root, &path, content.as_bytes()))
            .await
            .map_err(|error| FileSystemError::Io(error.to_string()))?
    }

    async fn remove_file(&self, path: &RelativePath) -> Result<bool, FileSystemError> {
        let root = self.root.clone();
        let path = path.as_path().to_owned();
        tokio::task::spawn_blocking(move || match root.remove_file(&path) {
            Ok(()) => Ok(true),
            Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(false),
            Err(error) => Err(map_io(&path, error)),
        })
        .await
        .map_err(|error| FileSystemError::Io(error.to_string()))?
    }
}

fn atomic_write(root: &Dir, path: &Path, content: &[u8]) -> Result<(), FileSystemError> {
    if let Some(parent) = path.parent()
        && !parent.as_os_str().is_empty()
    {
        root.create_dir_all(parent)
            .map_err(|error| map_io(parent, error))?;
    }

    let temp = temporary_path(path);
    let result = (|| {
        let mut file = root.create(&temp).map_err(|error| map_io(&temp, error))?;
        file.write_all(content)
            .map_err(|error| map_io(&temp, error))?;
        file.sync_all().map_err(|error| map_io(&temp, error))?;
        root.rename(&temp, root, path)
            .map_err(|error| map_io(path, error))?;
        Ok(())
    })();

    if result.is_err() {
        let _ = root.remove_file(&temp);
    }
    result
}

fn temporary_path(path: &Path) -> PathBuf {
    let mut value = path.as_os_str().to_owned();
    value.push(format!(".tmp-{}", std::process::id()));
    PathBuf::from(value)
}

fn map_io(path: &Path, error: io::Error) -> FileSystemError {
    let detail = format!("{}: {error}", path.display());
    match error.kind() {
        io::ErrorKind::NotFound => FileSystemError::NotFound(detail),
        io::ErrorKind::PermissionDenied => FileSystemError::Denied(detail),
        _ => FileSystemError::Io(detail),
    }
}

#[cfg(test)]
mod tests {
    use std::fs;

    use super::*;

    fn test_root(name: &str) -> PathBuf {
        std::env::temp_dir().join(format!(
            "audiagentic-fs-{name}-{}",
            std::process::id()
        ))
    }

    #[tokio::test]
    async fn component_can_only_use_relative_capability_paths() {
        let root = test_root("basic");
        let _ = fs::remove_dir_all(&root);
        fs::create_dir_all(&root).unwrap();
        let filesystem = NativeFileSystem::open(&root).unwrap();
        let path = RelativePath::new("config/app.txt").unwrap();

        filesystem
            .write_text_atomic(&path, "hello".to_owned())
            .await
            .unwrap();
        assert_eq!(
            filesystem.read_text(&path).await.unwrap().as_deref(),
            Some("hello")
        );
        assert!(filesystem.remove_file(&path).await.unwrap());
        assert!(!filesystem.remove_file(&path).await.unwrap());
        let _ = fs::remove_dir_all(&root);
    }

    #[cfg(unix)]
    #[tokio::test]
    async fn symlink_escape_is_denied_by_capability_directory() {
        use std::os::unix::fs::symlink;

        let root = test_root("symlink");
        let outside = test_root("outside");
        let _ = fs::remove_dir_all(&root);
        let _ = fs::remove_dir_all(&outside);
        fs::create_dir_all(&root).unwrap();
        fs::create_dir_all(&outside).unwrap();
        fs::write(outside.join("secret.txt"), "secret").unwrap();
        symlink(&outside, root.join("escape")).unwrap();

        let filesystem = NativeFileSystem::open(&root).unwrap();
        let path = RelativePath::new("escape/secret.txt").unwrap();
        assert!(filesystem.read_text(&path).await.is_err());

        let _ = fs::remove_dir_all(&root);
        let _ = fs::remove_dir_all(&outside);
    }
}
