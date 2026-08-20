use std::{fs, io::{self, Write}, path::{Path, PathBuf}};

use thiserror::Error;

#[derive(Debug, Error)]
pub enum FileStoreError {
    #[error("I/O error at {path}: {source}")]
    Io {
        path: PathBuf,
        #[source]
        source: io::Error,
    },
}

pub fn read_text(path: &Path) -> Result<Option<String>, FileStoreError> {
    match fs::read_to_string(path) {
        Ok(value) => Ok(Some(value)),
        Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(None),
        Err(source) => Err(FileStoreError::Io { path: path.to_owned(), source }),
    }
}

pub fn atomic_write_text(path: &Path, content: &str) -> Result<(), FileStoreError> {
    let parent = path.parent().unwrap_or_else(|| Path::new("."));
    fs::create_dir_all(parent).map_err(|source| FileStoreError::Io { path: parent.to_owned(), source })?;
    let temp = temporary_path(path);

    let result = (|| {
        let mut file = fs::File::create(&temp).map_err(|source| FileStoreError::Io { path: temp.clone(), source })?;
        file.write_all(content.as_bytes()).map_err(|source| FileStoreError::Io { path: temp.clone(), source })?;
        file.sync_all().map_err(|source| FileStoreError::Io { path: temp.clone(), source })?;
        fs::rename(&temp, path).map_err(|source| FileStoreError::Io { path: path.to_owned(), source })?;
        Ok(())
    })();

    if result.is_err() {
        let _ = fs::remove_file(&temp);
    }
    result
}

fn temporary_path(path: &Path) -> PathBuf {
    let mut temp = path.as_os_str().to_owned();
    temp.push(format!(".tmp-{}", std::process::id()));
    PathBuf::from(temp)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn absence_is_distinct_from_corruption_or_other_io_errors() {
        let dir = std::env::temp_dir().join(format!("audiagentic-filestore-{}", std::process::id()));
        let path = dir.join("state.txt");
        let _ = fs::remove_dir_all(&dir);
        assert_eq!(read_text(&path).unwrap(), None);
        atomic_write_text(&path, "first").unwrap();
        atomic_write_text(&path, "second").unwrap();
        assert_eq!(read_text(&path).unwrap().as_deref(), Some("second"));
        let _ = fs::remove_dir_all(&dir);
    }
}
